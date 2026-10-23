"""MCP 工具 list_local_images：列出可用图片。

作用点：**定位文件**。用户只说「我截了张拓扑图」时，用它扫桌面/下载/图片目录
找出最近的图片，而不是反复追问路径。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def list_local_images(directory: str = "", limit: int = 20) -> str:
    """列出可用的图片文件（用户提到截图/拓扑图但未给出完整路径时用）。

    Args:
        directory: 指定目录；留空则扫描桌面 / 下载 / 图片 / 文档与项目目录
        limit: 最多返回条数，默认 20
    """
    from core import vision

    try:
        items = vision.list_local_images(directory or None, limit=max(1, limit))
    except Exception as e:  # noqa: BLE001  工具不抛异常
        return f"图片枚举失败：{type(e).__name__}: {e}"
    if not items:
        return "没有找到图片文件，请向用户索取拓扑图的完整路径。"

    lines = [f"找到 {len(items)} 张图片（按修改时间倒序）："]
    for it in items:
        lines.append(f"  - {it['path']}（{it['mb']} MB，{it['mtime']}）")
    return "\n".join(lines)
