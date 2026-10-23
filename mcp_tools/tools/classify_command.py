"""MCP 工具 classify_command：只做风险分级，不执行。

作用点：**预检**。让模型在下发配置命令前先问一句「这条会不会被拦」，
从而提前把影响讲清楚，而不是等被拒后再解释。

归属服务端：Network-Device-Serial（mcp_tools/device_server.py）
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def classify_command(command: str) -> str:
    """判断一条设备命令的风险等级，不执行任何操作。

    分级规则：allow（只读，可直接执行）/ confirm（配置类，需用户同意）/ block（破坏性，禁止执行）。

    Args:
        command: 待评估的命令，例如 "undo vlan 100"
    """
    from core.command_guard import classify

    if not (command or "").strip():
        return "command 不能为空"
    return classify(command)["text"]
