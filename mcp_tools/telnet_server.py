"""Telnet MCP 服务端：让智能体用用户提供的凭据远程登录设备执行命令。

本文件只做**注册中心**：建 FastMCP 实例，把 mcp_tools/tools/ 下单工具模块
装配进来。工具实现不在这里——一个工具一个文件（见 mcp_tools/tools/__init__.py）。

工具列表（实现文件 → 工具名）：
    tools/check_telnet.py        check_telnet(host, port)
        只探测端口连通性与 banner，不下发任何命令（只读，安全）
    tools/exec_telnet_command.py exec_telnet_command(command, host, username, password, port, ...)
        连接 → 自动登录 → 执行命令 → 返回回显
        安全策略与串口通道完全一致（共用 core/command_guard.py）：
            allow   display / show / ping / tracert → 直接执行
            confirm sysname / vlan / interface 等   → 必须带 confirm=true 才执行
            block   undo / shutdown / delete / reset / reboot → 直接拦截
        每次裁决写入 logs/command_audit.log

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

mcp = FastMCP("Network-Device-Telnet")

# ---------------------------------------------------------------- 工具装配
# 一个工具一个文件：从 mcp_tools/tools/<工具名>.py 导入同名函数后注册。
# 新增工具 = 新文件 + 这里加一行，不碰已有工具的实现。
from mcp_tools.tools.check_telnet import check_telnet  # noqa: E402
from mcp_tools.tools.exec_telnet_command import exec_telnet_command  # noqa: E402

mcp.tool(check_telnet)
mcp.tool(exec_telnet_command)


if __name__ == "__main__":
    mcp.run(transport="stdio")
