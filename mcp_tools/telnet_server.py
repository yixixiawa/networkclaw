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
from core.command_guard import LEVEL_CN, audit, check  # noqa: E402

mcp = FastMCP("Network-Device-Telnet")

MAX_OUTPUT = 6000
DEFAULT_TELNET_PORT = 23


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return (text[:limit]
            + f"\n...（回显共 {len(text)} 字，已截断；可用 display ... | include 缩小范围）")


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
        return message

    sess = None
    try:
        sess = device_conn.open_telnet(
            host.strip(), port=port, username=username, password=password,
            enable_password=enable_password, timeout=max(5, timeout),
            disable_paging=disable_paging,
        )
        output = sess.exec_command(command, timeout=max(5, timeout))
        audit(command, decision, transport="telnet", target=target,
              confirmed=confirm, executed=True)
    except Exception as e:
        audit(command, decision, transport="telnet", target=target,
              confirmed=confirm, executed=False, extra=f"{type(e).__name__}: {e}")
        return f"Telnet 执行失败：{type(e).__name__}: {e}"
    finally:
        if sess is not None:
            sess.close()

    return (f"[{LEVEL_CN[decision['level']]}] {target} 执行：{command}\n"
            f"———— 回显 ————\n{_truncate(output) if output else '(设备无回显)'}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
