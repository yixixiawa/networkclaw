"""设备手册 MCP 服务端：让**本地模型自己**给设备建档、维护手册与查阅历史。

本文件只做**注册中心**：建 FastMCP 实例，把 mcp_tools/tools/ 下单工具模块
装配进来。工具实现不在这里——一个工具一个文件（见 mcp_tools/tools/__init__.py）。

设计意图（用户要求）：设备手册不是仓库里写死的内容，而是模型在运行期
「遇到哪台设备、就为它建一份档」——首次接触时探测/问询得到的信息填进骨架，
配置验证有效后再把命令序列与踩过的坑沉淀回去。

**一个对话一套技能**（2026-10 起）：
    手册与命令历史按会话隔离，布局由用户指定：

        session/<会话标识>/skill/<设备名>/SKILL.md          手册
        session/<会话标识>/skill/<设备名>/history.jsonl     命令历史

    「当前会话」由 core/session_skills.current() 解析（主程序开对话时写入
    session/.current，本服务端每次调用前读取），因此 GUI 里切换会话后无需
    重连，工具立刻跟随新会话。其他对话的设备记忆**不会**出现在这里——
    这是刻意隔离，避免模型把别处对话的结论当成本对话的经验。

工具列表（实现文件 → 工具名）：
    tools/list_device_manuals.py          list_device_manuals()
        看当前会话里哪些设备已有手册、哪些还没有
    tools/read_device_manual.py           read_device_manual(device[, session])
        操作某台设备前先读它：常用配置、注意事项
    tools/create_device_manual.py         create_device_manual(device, ...)
        首次接触某设备时建档（信息**不要臆造**）
    tools/update_device_manual_section.py update_device_manual_section(device, section, text, ...)
        把验证有效的命令序列 / 踩过的坑写回手册
    tools/recent_device_history.py        recent_device_history(device[, n, session])
        查看该设备最近的命令历史（由工具层自动记录）
    tools/list_session_skills.py          list_session_skills()
        查看所有对话各自的设备技能分布（只读；回答「上次那个会话里」用）

运行方式（stdio，由 MCP 客户端拉起）：
    python mcp_tools/manual_server.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("Network-Device-Manual")

# ---------------------------------------------------------------- 工具装配
# 一个工具一个文件：从 mcp_tools/tools/<工具名>.py 导入同名函数后注册。
from mcp_tools.tools.create_device_manual import create_device_manual  # noqa: E402
from mcp_tools.tools.list_device_manuals import list_device_manuals  # noqa: E402
from mcp_tools.tools.list_session_skills import list_session_skills  # noqa: E402
from mcp_tools.tools.read_device_manual import read_device_manual  # noqa: E402
from mcp_tools.tools.recent_device_history import recent_device_history  # noqa: E402
from mcp_tools.tools.update_device_manual_section import (  # noqa: E402
    update_device_manual_section,
)

mcp.tool(list_device_manuals)
mcp.tool(list_session_skills)
mcp.tool(read_device_manual)
mcp.tool(create_device_manual)
mcp.tool(update_device_manual_section)
mcp.tool(recent_device_history)


if __name__ == "__main__":
    mcp.run(transport="stdio")
