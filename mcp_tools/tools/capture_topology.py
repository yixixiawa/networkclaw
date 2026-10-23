"""MCP 工具 capture_topology：实时截屏 + 识读当前拓扑。

作用点：**主动看屏幕**。用户提到「当前拓扑 / 现在的网络」且没给截图时用它：
自动截取 eNSP / 虚拟机窗口 → OpenCV 预处理 → 本地多模态模型识读。
画面与上次一致时直接复用上次结论（避免每次重跑推理）。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def capture_topology(keyword: str = "", force: bool = False) -> str:
    """实时查看当前网络拓扑：自动截取 eNSP / 虚拟机（VMware 等）窗口画面，
    用 OpenCV 预处理后交给本地多模态模型识读，返回结构化拓扑描述。

    什么时候用：用户提到「当前拓扑 / 现在的网络 / 刚画好的拓扑」且没有给截图，
    或用户表示拓扑发生了变化需要重新查看时。

    注意：截图只保存在本机（logs/captures/），识读由本地模型完成；若目标窗口
    被遮挡会短暂把它切到前台。画面与上次一致时会直接复用上次结论。

    Args:
        keyword: 目标窗口标题关键字（如 "vmware" / "ensp"）；留空按内置关键字表匹配
        force: True 时即使画面没变化也强制重新识读
    """
    from core import auto_topology

    try:
        result = auto_topology.auto_inspect(keyword=(keyword or "").strip() or None,
                                            force=bool(force), show_thinking=False)
    except Exception as e:  # noqa: BLE001  工具不抛异常
        return f"拓扑巡检异常：{type(e).__name__}: {e}"
    if not result.get("ok"):
        return (f"自动巡检未成功：{result.get('message', '')}\n"
                f"（可让用户手动截图后用 analyze_topology_image 识读）")
    return auto_topology.render_result(result)
