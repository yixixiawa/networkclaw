"""MCP 工具 check_telnet：探测目标设备 Telnet 端口是否可达（只读）。

作用点只有一个：**连通性探测**。不下发任何命令，因此永远属于 allow 级，
模型可以自由调用而无需用户确认。

归属服务端：Network-Device-Telnet（mcp_tools/telnet_server.py）
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)

DEFAULT_TELNET_PORT = 23


def check_telnet(host: str, port: int = DEFAULT_TELNET_PORT) -> str:
    """探测目标设备的 Telnet 端口是否可达（只读，不会下发任何配置命令）。

    Args:
        host: 设备 IP 或主机名，例如 192.168.183.200
        port: Telnet 端口，默认 23
    """
    if not (host or "").strip():
        return "host 不能为空"

    from core import device_conn

    info = device_conn.probe_tcp(host.strip(), port)
    if not info["ok"]:
        return (f"无法连接 {info['host']}:{info['port']}（耗时 {info['elapsed']}s）：{info['error']}\n"
                f"排查建议：① 设备是否已开启 Telnet（Huawei/H3C：telnet server enable）；"
                f"② 中间设备/ACL 是否放通 23 端口；③ VTY 用户是否允许该源地址登录。")

    banner = info.get("banner") or "(设备未主动发送 banner，属正常现象)"
    # 探测成功即登记访问：后续命令历史才能把 host:port 归到正确设备名下
    from core.device_registry import record_access

    record_access("telnet", host=info["host"], port=info["port"])
    return f"{info['host']}:{info['port']} 端口可达（耗时 {info['elapsed']}s）。banner：{banner}"
