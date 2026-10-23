"""串口（Console）MCP 服务端：让智能体通过串口线连接到目标设备执行命令。

本文件只做**注册中心**：建 FastMCP 实例，把 mcp_tools/tools/ 下单工具模块
装配进来。工具实现不在这里——一个工具一个文件（见 mcp_tools/tools/__init__.py）。

工具列表（实现文件 → 工具名）：
    tools/list_serial_ports.py  list_serial_ports()
        列出本机可用串口（COM3 等），执行前先看这个确认端口号
    tools/classify_command.py   classify_command(command)
        只做风险分级、不执行：allow / confirm / block
        建议模型在下发配置命令前先调它，这样能提前把影响讲清楚
    tools/exec_command.py       exec_command(command, port, baudrate, confirm, timeout)
        打开串口 → 执行命令 → 返回回显
        安全策略（见 core/command_guard.py）：
            allow   display / show / ping / tracert 等只读命令 → 直接执行
            confirm sysname / vlan / interface 等配置命令 → 必须确认
            block   undo / shutdown / delete / reset / reboot 等 → 直接拦截
        每次裁决都写入 logs/command_audit.log
    tools/recent_audit.py       recent_audit(n)
        查看最近的命令执行审计记录

运行方式（stdio，由 MCP 客户端拉起）：
    python mcp_tools/device_server.py
"""
import sys
from pathlib import Path

# 保证从任意工作目录被 MCP 客户端拉起时都能导入 core 包
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("Network-Device-Serial")

# ---------------------------------------------------------------- 工具装配
# 一个工具一个文件：从 mcp_tools/tools/<工具名>.py 导入同名函数后注册。
from mcp_tools.tools.classify_command import classify_command  # noqa: E402
from mcp_tools.tools.exec_command import exec_command  # noqa: E402
from mcp_tools.tools.list_serial_ports import list_serial_ports  # noqa: E402
from mcp_tools.tools.recent_audit import recent_audit  # noqa: E402

mcp.tool(list_serial_ports)
mcp.tool(classify_command)
mcp.tool(exec_command)
mcp.tool(recent_audit)


if __name__ == "__main__":
    mcp.run(transport="stdio")
