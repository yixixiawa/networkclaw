"""Telnet MCP 服务端：让智能体用用户提供的凭据远程登录设备执行命令。

工具列表：
1. check_telnet(host, port)
   - 只探测 TCP 23 端口连通性与 banner，不下发任何命令（只读，安全）
2. exec_telnet_command(command, host, username, password, port, enable_password, confirm)
   - 连接 → 自动登录（用户名 → 密码 → 可选 enable）→ 执行一条命令 → 返回回显
   - 安全策略与串口通道完全一致（共用 core/command_guard.py）：
       allow   display / show / ping / tracert → 直接执行
       confirm sysname / vlan / interface 等   → 必须带 confirm=true 才执行
       block   undo / shutdown / delete / reset / reboot → 直接拦截
   - 每次裁决写入 logs/command_audit.log

安全提示：
    - 连接参数一律由用户提供，不要自行猜测 IP / 用户名 / 密码
    - 密码不会写入审计日志，只记录目标地址与命令
    - 本工具只执行用户明确要求的单条命令，不做自动化批量变更

运行方式（stdio，由 MCP 客户端拉起）：
    python mcp_tools/telnet_server.py
"""
import sys
from pathlib import Path

# 保证从任意工作目录被 MCP 客户端拉起时都能导入 core 包
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastmcp import FastMCP  # noqa: E402

from core import device_conn  # noqa: E402
from core.command_guard import LEVEL_CN, audit, check, split_commands  # noqa: E402

mcp = FastMCP("Network-Device-Telnet")

MAX_OUTPUT = 6000
DEFAULT_TELNET_PORT = 23


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return (text[:limit]
            + f"\n...（回显共 {len(text)} 字，已截断；可用 display ... | include 缩小范围）")


def _record(host: str, port: int, command: str, level: str, confirmed: bool,
            executed: bool, result: str = "", extra: str = "") -> str:
    """访问登记 + 命令历史归档（确定性落盘，不依赖模型自觉；失败静默不影响执行）。

    设备名解析：种子清单里 host:port 匹配到的名字 > 登记时绑定的名字 > 地址兜底。
    返回归档到的文件名（无则空串），供回显里告知用户「已记到哪里」。
    """
    name = ""
    try:
        from core import device_manual, device_registry
        device_registry.record_access("telnet", host=host, port=port)
        name = device_registry.resolve_name("telnet", host=host, port=port)
        device_manual.append_history(name, command, result, transport="telnet",
                                     target=f"{host}:{port}", level=level,
                                     confirmed=confirmed, executed=executed,
                                     extra=extra)
    except Exception:
        return ""
    return f"data/device_history/{name}.jsonl" if name else ""


@mcp.tool
def check_telnet(host: str, port: int = DEFAULT_TELNET_PORT) -> str:
    """探测目标设备的 Telnet 端口是否可达（只读，不会下发任何配置命令）。

    Args:
        host: 设备 IP 或主机名，例如 192.168.183.200
        port: Telnet 端口，默认 23
    """
    if not (host or "").strip():
        return "host 不能为空"
    info = device_conn.probe_tcp(host.strip(), port)
    if not info["ok"]:
        return (f"无法连接 {info['host']}:{info['port']}（耗时 {info['elapsed']}s）：{info['error']}\n"
                f"排查建议：① 设备是否已开启 Telnet（Huawei/H3C：telnet server enable）；"
                f"② 中间设备/ACL 是否放通 23 端口；③ VTY 用户是否允许该源地址登录。")
    banner = info.get("banner") or "(设备未主动发送 banner，属正常现象)"
    if info["ok"]:
        from core.device_registry import record_access
        record_access("telnet", host=info["host"], port=info["port"])
    return f"{info['host']}:{info['port']} 端口可达（耗时 {info['elapsed']}s）。banner：{banner}"


@mcp.tool
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
    command = (command or "").strip()
    if not command:
        return "command 不能为空"
    if not (host or "").strip():
        return "host 不能为空，请向用户索取设备 IP"

    target = f"{host}:{port}"
    allowed, message, decision = check(command, confirmed=confirm)
    if not allowed:
        audit(command, decision, transport="telnet", target=target,
              confirmed=confirm, executed=False)
        _record(host.strip(), port, command, decision["level"], confirm, False,
                result=message)
        return message

    sess = None
    try:
        sess = device_conn.open_telnet(
            host.strip(), port=port, username=username, password=password,
            enable_password=enable_password, timeout=max(5, timeout),
            disable_paging=disable_paging,
        )
        # 支持 `;`/换行串联的多条命令：同一会话内逐条执行（视图状态自然延续）
        parts = split_commands(command)
        if len(parts) == 1:
            output = sess.exec_command(command, timeout=max(5, timeout))
        else:
            chunks = []
            for part in parts:
                r = sess.exec_command(part, timeout=max(5, timeout))
                chunks.append(f"$ {part}\n{r}" if r else f"$ {part}\n(无回显)")
            output = "\n".join(chunks)
        audit(command, decision, transport="telnet", target=target,
              confirmed=confirm, executed=True)
        filed = _record(host.strip(), port, command, decision["level"], confirm, True,
                        result=output)
    except Exception as e:
        audit(command, decision, transport="telnet", target=target,
              confirmed=confirm, executed=False, extra=f"{type(e).__name__}: {e}")
        _record(host.strip(), port, command, decision["level"], confirm, False,
                result=f"{type(e).__name__}: {e}")
        return f"Telnet 执行失败：{type(e).__name__}: {e}"
    finally:
        if sess is not None:
            sess.close()

    tail = f"\n（已记入 {filed}）" if filed else ""
    # 走到这里说明命令已真正下发（confirm 级带了 confirm=true 也会放行）。
    # 这里**不能**回写「[需确认]」前缀——实测模型看到它会误判成"命令被拒绝"，
    # 然后原地打转反复重发同一条命令。执行成功就只说执行成功。
    errs = [ln.strip() for ln in (output or "").splitlines()
            if ln.strip().lower().startswith(("error", "错误"))]
    err_note = ("\n\n[设备报错] 必须据此修正命令，不要原样重发：\n"
                + "\n".join(errs[:6])) if errs else ""
    # 光把报错丢回给模型没用——9B 模型看不懂英文报错，只会原样重发。
    # 附上对应的标准解法，实测能把空转从 8 轮压到 1~2 轮。
    try:
        from core.cmd_hints import format_hints

        err_note += format_hints(output or "")
    except Exception:  # noqa: BLE001
        pass
    return (f"[已执行] {target} 执行：{command}\n"
            f"———— 回显 ————\n{_truncate(output) if output else '(设备无回显)'}"
            f"{err_note}{tail}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
