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
                        disable_paging: bool = True, session: str = "",
                        confirmation_token: str = "") -> str:
    """通过 Telnet 登录目标设备并执行一条命令。

    Args:
        command: 要执行的命令，例如 "display current-configuration | include ssh"
        host: 设备 IP 或主机名（必须由用户提供，不要猜测）
        username: 登录用户名；设备未启用用户名认证时留空
        password: 登录密码
        port: Telnet 端口，默认 23
        enable_password: Cisco 等设备从用户视图进入特权模式（enable）所需的密码，可选
            confirm: 兼容字段；单独传 true 不能代表用户确认
            confirmation_token: GUI 用户确认后发放的一次性授权 token
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
    allowed, message, decision = check(
        command, confirmed=confirm, confirmation_token=confirmation_token,
        transport="telnet", target=target, session=session)
    if not allowed:
        audit(command, decision, transport="telnet", target=target,
              confirmed=confirm, executed=False)
        record_telnet(host, port, command, decision["level"], confirm, False,
                      result=message, session=session)
        return message

    sess = None
    try:
        sess = device_conn.open_telnet(
            host, port=port, username=username, password=password,
            enable_password=enable_password, timeout=max(5, timeout),
            disable_paging=disable_paging,
        )
        results = _run_parts(sess, command, max(5, timeout))
    except Exception as e:  # noqa: BLE001  工具不抛异常，转可读文本
        audit(command, decision, transport="telnet", target=target,
              confirmed=confirm, executed=False, extra=f"{type(e).__name__}: {e}")
        record_telnet(host, port, command, decision["level"], confirm, False,
                  result=f"{type(e).__name__}: {e}", session=session)
        return f"Telnet 执行失败：{type(e).__name__}: {e}"
    finally:
        if sess is not None:
            sess.close()

    # 逐条审计 + 逐条归档（plan 阶段二）：复合命令不能只记整串，
    # 否则 history.jsonl 里查不到「实际下发的是哪一条、各自回显是什么」。
    # 注意：授权裁决仍按整串的最高风险一次判定（confirmation_token 是一次性的，
    # 不能逐条消费）；这里复用该裁决给每一条做审计记录。
    chunks: list[str] = []
    filed_list: list[str] = []
    for part, output, ok in results:
        audit(part, decision, transport="telnet", target=target,
              confirmed=confirm, executed=ok,
              extra="" if ok else output)
        filed_list.append(record_telnet(host, port, part, decision["level"],
                                        confirm, ok, result=output,
                                        session=session))
        chunks.append(f"$ {part}\n{output}" if output else f"$ {part}\n(无回显)")
    output = "\n".join(chunks)

    filed = [p for p in filed_list if p]
    tail = f"\n（已记入 {len(filed)}/{len(filed_list)} 条历史）" if filed else ""
    if len(filed) != len(filed_list):
        tail += "\n（注意：部分历史归档失败，详见 logs/archive_errors.log）"
    return (f"[已执行] {target} 执行：{command}\n"
            f"———— 回显 ————\n{truncate(output) if output else '(设备无回显)'}"
            f"{_hint(output)}{tail}")
