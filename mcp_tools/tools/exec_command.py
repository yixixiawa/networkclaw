"""MCP 工具 exec_command：通过串口（Console）执行一条命令。

作用点：**串口通道的一条命令下发与回显**。与 telnet 版是同构的，差别只在
连接层（device_conn.open_serial）与身份（COMx 而非 host:port）。

安全策略（与 Telnet 共用 core/command_guard.py）：
    allow   display / show / ping / tracert → 直接执行
    confirm sysname / vlan / interface 等   → 必须 confirm=true
    block   undo / shutdown / delete / reset / reboot → 硬拦

典型用法：
    exec_command("display version", port="COM3")
    exec_command("sysname SW-Core-01", port="COM3")                 # 第一次被拦下要确认
    exec_command("sysname SW-Core-01", port="COM3", confirm=True)   # 用户同意后再执行

归属服务端：Network-Device-Serial（mcp_tools/device_server.py）
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)

from mcp_tools.tools._archive import record_serial
from mcp_tools.tools._bootstrap import truncate

DEFAULT_BAUDRATE = 9600    # 网络设备 Console 口默认波特率


def _run(sess, command: str, timeout: int) -> str:
    """在同一会话里执行命令；多条（; 或换行）逐条执行并标注各自回显。"""
    from core.command_guard import split_commands

    parts = split_commands(command)
    if len(parts) == 1:
        return sess.exec_command(command, timeout=timeout)
    chunks = []
    for part in parts:
        r = sess.exec_command(part, timeout=timeout)
        chunks.append(f"$ {part}\n{r}" if r else f"$ {part}\n(无回显)")
    return "\n".join(chunks)


def exec_command(command: str, port: str, baudrate: int = DEFAULT_BAUDRATE,
                 confirm: bool = False, timeout: int = 20,
                 disable_paging: bool = True) -> str:
    """通过串口（Console）在目标设备上执行一条命令。

    Args:
        command: 要执行的命令；多条命令请分次调用，不要用分号串联
        port: 串口号，例如 COM3（先用 list_serial_ports 查询）
        baudrate: 波特率，默认 9600
        confirm: 仅当该命令被判定为「需确认」且用户已明确同意时才传 true
        timeout: 等待回显的超时秒数，默认 20（ping 等耗时命令可加大）
        disable_paging: 是否自动关闭长回显分页，默认 true
    """
    from core import device_conn
    from core.command_guard import LEVEL_CN, audit, check

    command = (command or "").strip()
    if not command:
        return "command 不能为空"
    if not (port or "").strip():
        return "port 不能为空，请先用 list_serial_ports 查询可用串口"

    port = port.strip().upper()
    allowed, message, decision = check(command, confirmed=confirm)
    if not allowed:
        audit(command, decision, transport="serial", target=port,
              confirmed=confirm, executed=False)
        record_serial(port, command, decision["level"], confirm, False, result=message)
        return message

    sess = None
    try:
        sess = device_conn.open_serial(port, baudrate=baudrate, timeout=max(5, timeout),
                                       disable_paging=disable_paging)
        output = _run(sess, command, max(5, timeout))
        audit(command, decision, transport="serial", target=port,
              confirmed=confirm, executed=True)
        filed = record_serial(port, command, decision["level"], confirm, True,
                              result=output)
    except Exception as e:  # noqa: BLE001  工具不抛异常
        audit(command, decision, transport="serial", target=port,
              confirmed=confirm, executed=False, extra=f"{type(e).__name__}: {e}")
        record_serial(port, command, decision["level"], confirm, False,
                      result=f"{type(e).__name__}: {e}")
        return f"串口执行失败：{type(e).__name__}: {e}"
    finally:
        if sess is not None:
            sess.close()

    tail = f"\n（已记入 {filed}）" if filed else ""
    return (f"[{LEVEL_CN[decision['level']]}] {port} 执行：{command}\n"
            f"———— 回显 ————\n{truncate(output) if output else '(设备无回显)'}{tail}")
