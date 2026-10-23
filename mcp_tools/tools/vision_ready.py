"""MCP 工具 vision_ready：检查识图能力是否就绪。

作用点：**自查前置条件**。识图依赖 llama-server 以多模态方式启动（加载 mmproj），
没加载就调用识图只会得到无意义的结果。先问一句，省一次失败。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def vision_ready() -> str:
    """检查图像识别能力是否就绪（llama-server 是否已加载 mmproj 视觉投影文件）。"""
    from core import vision

    status = vision.vision_status()
    mmproj = vision.find_mmproj()
    lines = [
        f"视觉能力：{'可用' if status['available'] else ('不可用' if status['available'] is False else '待确认')}",
        f"判据：{status['detail']}",
        f"mmproj 文件：{mmproj if mmproj else '未找到'}",
    ]
    if not mmproj:
        lines.append(vision.mmproj_hint())
    return "\n".join(lines)
