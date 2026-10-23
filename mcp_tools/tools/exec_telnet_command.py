"""MCP 工具 exec_telnet_command：通过 Telnet 登录设备并执行一条命令。

作用点：**一条命令的下发与回显**（含安全裁决、审计、历史归档）。
这是整个项目最核心的写操作入口，安全边界全部经 core/command_guard.py：
    allow   display / show / ping / tracert → 直接执行
    confirm sysname / vlan / interface 等   → 必须 confirm=true 才执行
    block   undo / shutdown / delete / reset / reboot → 硬拦

几个实测踩过的坑（改这里前务必读）：
1. 执行成功后**不要**回写「[需确认]」前缀。模型看到会误判成"被拒绝"，
   然后原地反复重发同一条命令（实测空转 8 轮）。
2. 设备英文报错对 9B 模型没用，它只会原样重发。所以要附 core/cmd_hints 的
   标准解法，实测把空转从 8 轮压到 1~2 轮。
3. 多命令（`;`/换行）在同一会话内逐条执行，视图状态自然延续
   （例如 `system-view` 后接 `vlan 10` 才有意义）。

归属服务端：Network-Device-Telnet（mcp_tools/telnet_server.py）
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)

from mcp_tools.tools._archive import record_telnet
from mcp_tools.tools._bootstrap import truncate

DEFAULT_TELNET_PORT = 23


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


def _hint(output: str) -> str:
    """收集设备报错行并附上标准解法（模型看不懂英文报错，需要明示）。"""
    errs = [ln.strip() for ln in (output or "").splitlines()
            if ln.strip().lower().startswith(("error", "错误"))]
    note = ""
    if errs:
        note = "\n\n[设备报错] 必须据此修正命令，不要原样重发：\n" + "\n".join(errs[:6])
    try:
        from core.cmd_hints import format_hints

        note += format_hints(output or "")
    except Exception:  # noqa: BLE001  提示是增强项，缺失不影响执行
        pass
    return note


def exec_telnet_command(command: str, host: str, username: str = "", password: str = "",
                        port: int = DEFAULT_TELNET_PORT, enable_password: str = "",
                        confirm: bool = False, timeout: int = 20,
                        disable_paging: bool = True) -> str:
    """通过 Telnet 登录目标设备并执行一条命令。

    Args:
        command: 要执行的命令，例如 "display current-configuration | include ssh"
        host: 设备 IP 或主机名（必须由用户提供，不要猜测）
        username: 登录用户名；设备未启用用户名认证时留空
        password: 登录密码
        port: Telnet 端口，默认 23
        enable_password: Cisco 等设备从用户视图进入特权模式（enable）所需的密码，可选
        confirm: 仅当命令被判定为「需确认」且用户已明确同意时才传 true
        timeout: 等待回显的超时秒数，默认 20
        disable_paging: 是否自动关闭长回显分页，默认 true
    """
    from core import device_conn
    from core.command_guard import audit, check

    command = (command or "").strip()
    if not command:
        return "command 不能为空"
    if not (host or "").strip():
        return "host 不能为空，请向用户索取设备 IP"

    host = host.strip()
    target = f"{host}:{port}"
    allowed, message, decision = check(command, confirmed=confirm)
    if not allowed:
        audit(command, decision, transport="telnet", target=target,
              confirmed=confirm, executed=False)
        record_telnet(host, port, command, decision["level"], confirm, False,
                      result=message)
        return message

    sess = None
    try:
        sess = device_conn.open_telnet(
            host, port=port, username=username, password=password,
            enable_password=enable_password, timeout=max(5, timeout),
            disable_paging=disable_paging,
        )
        output = _run(sess, command, max(5, timeout))
        audit(command, decision, transport="telnet", target=target,
              confirmed=confirm, executed=True)
        filed = record_telnet(host, port, command, decision["level"], confirm, True,
                              result=output)
    except Exception as e:  # noqa: BLE001  工具不抛异常，转可读文本
        audit(command, decision, transport="telnet", target=target,
              confirmed=confirm, executed=False, extra=f"{type(e).__name__}: {e}")
        record_telnet(host, port, command, decision["level"], confirm, False,
                      result=f"{type(e).__name__}: {e}")
        return f"Telnet 执行失败：{type(e).__name__}: {e}"
    finally:
        if sess is not None:
            sess.close()

    tail = f"\n（已记入 {filed}）" if filed else ""
    return (f"[已执行] {target} 执行：{command}\n"
            f"———— 回显 ————\n{truncate(output) if output else '(设备无回显)'}"
            f"{_hint(output)}{tail}")
