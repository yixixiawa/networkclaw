"""MCP 工具 list_serial_ports：列出本机可用串口。

作用点：**枚举**。执行任何串口命令前先看它确认端口号。

归属服务端：Network-Device-Serial（mcp_tools/device_server.py）
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def list_serial_ports() -> str:
    """列出本机可用串口设备（执行串口命令前先用它确认端口号）。"""
    from core import device_conn

    try:
        ports = device_conn.list_serial_ports()
    except Exception as e:  # noqa: BLE001  工具不抛异常
        return f"串口枚举失败：{type(e).__name__}: {e}"
    if not ports:
        return ("未发现可用串口。请确认：① 串口线/USB 转串口已插入；"
                "② 驱动已安装；③ 端口未被 SecureCRT / 串口助手等程序占用。")

    lines = [f"发现 {len(ports)} 个串口："]
    for p in ports:
        lines.append(f"  - {p['device']}：{p['description']}（{p['hwid']}）")
    return "\n".join(lines)
