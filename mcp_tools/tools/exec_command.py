"""MCP 工具 exec_command：通过串口（Console）执行一条命令。

作用点：**串口通道的一条命令下发与回显**。与 telnet 版是同构的，差别只在
连接层（device_conn.open_serial）与身份（COMx 而非 host:port）。

安全策略（与 Telnet 共用 core/command_guard.py）：
    allow   display / show / ping / tracert → 直接执行
    confirm sysname / vlan / interface 等   → 必须经过 GUI confirmation_token
    block   undo / shutdown / delete / reset / reboot → 硬拦

典型用法：
    exec_command("display version", port="COM3")
    exec_command("sysname SW-Core-01", port="COM3")                 # 第一次被拦下要确认
    exec_command("sysname SW-Core-01", port="COM3", confirmation_token="...")

归属服务端：Network-Device-Serial（mcp_tools/device_server.py）
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)

from mcp_tools.tools._archive import record_serial
from mcp_tools.tools._bootstrap import truncate

DEFAULT_BAUDRATE = 9600    # 网络设备 Console 口默认波特率


def _run_parts(sess, command: str, timeout: int) -> list[tuple[str, str, bool]]:
    """在同一会话里逐条执行命令（`;`/换行拆分），返回 `[(命令, 回显, 是否下发成功)]`。

    会话是状态机（视图切换会延续），某条命令异常后继续下发没有意义——
    首条失败即停，剩余部分标成「未执行」交回调用方，保证**每一条**都有审计与归档。
    """
    from core.command_guard import split_commands

    parts = split_commands(command)
    results: list[tuple[str, str, bool]] = []
    failed = False
    for part in parts:
        if failed:
            results.append((part, "(未执行：前序命令失败，会话状态不可靠)", False))
            continue
        try:
            r = sess.exec_command(part, timeout=timeout)
            results.append((part, r or "", True))
        except Exception as e:  # noqa: BLE001  单条失败不中断归档
            results.append((part, f"{type(e).__name__}: {e}", False))
            failed = True
    return results


def exec_command(command: str, port: str, baudrate: int = DEFAULT_BAUDRATE,
                 confirm: bool = False, timeout: int = 20,
                 disable_paging: bool = True, session: str = "",
                 confirmation_token: str = "") -> str:
    """通过串口（Console）在目标设备上执行一条命令。

    Args:
        command: 要执行的命令；多条命令请分次调用，不要用分号串联
        port: 串口号，例如 COM3（先用 list_serial_ports 查询）
        baudrate: 波特率，默认 9600
        confirm: 兼容字段；单独传 true 不能代表用户确认
        confirmation_token: GUI 用户确认后发放的一次性授权 token
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
    allowed, message, decision = check(
        command, confirmed=confirm, confirmation_token=confirmation_token,
        transport="serial", target=port, session=session)
    if not allowed:
        audit(command, decision, transport="serial", target=port,
              confirmed=confirm, executed=False)
        record_serial(port, command, decision["level"], confirm, False,
                      result=message, session=session)
        return message

    sess = None
    try:
        sess = device_conn.open_serial(port, baudrate=baudrate, timeout=max(5, timeout),
                                       disable_paging=disable_paging)
        results = _run_parts(sess, command, max(5, timeout))
    except Exception as e:  # noqa: BLE001  工具不抛异常
        audit(command, decision, transport="serial", target=port,
              confirmed=confirm, executed=False, extra=f"{type(e).__name__}: {e}")
        record_serial(port, command, decision["level"], confirm, False,
                      result=f"{type(e).__name__}: {e}", session=session)
        return f"串口执行失败：{type(e).__name__}: {e}"
    finally:
        if sess is not None:
            sess.close()

    # 逐条审计 + 逐条归档（plan 阶段二）：与 Telnet 版同构；授权裁决仍按
    # 整串最高风险一次判定（confirmation_token 一次性，不能逐条消费）。
    chunks: list[str] = []
    filed_list: list[str] = []
    for part, output, ok in results:
        audit(part, decision, transport="serial", target=port,
              confirmed=confirm, executed=ok,
              extra="" if ok else output)
        filed_list.append(record_serial(port, part, decision["level"],
                                        confirm, ok, result=output,
                                        session=session))
        chunks.append(f"$ {part}\n{output}" if output else f"$ {part}\n(无回显)")
    output = "\n".join(chunks)

    filed = [p for p in filed_list if p]
    tail = f"\n（已记入 {len(filed)}/{len(filed_list)} 条历史）" if filed else ""
    if len(filed) != len(filed_list):
        tail += "\n（注意：部分历史归档失败，详见 logs/archive_errors.log）"
    return (f"[{LEVEL_CN[decision['level']]}] {port} 执行：{command}\n"
            f"———— 回显 ————\n{truncate(output) if output else '(设备无回显)'}{tail}")
