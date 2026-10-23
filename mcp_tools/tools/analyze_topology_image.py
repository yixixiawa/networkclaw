"""MCP 工具 analyze_topology_image：识读一张拓扑图。

作用点：**看图**。输入图片路径，输出设备清单（名称/型号/角色/IP）、连接关系
（接口对接口）、网段与 VLAN、风险点。**看图猜的**结论与 topology_server 的
实测结论可能冲突，冲突时以实测为准。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def analyze_topology_image(image_path: str, question: str = "") -> str:
    """识读网络拓扑图，输出设备清单、连接关系、IP/网段与风险点。

    Args:
        image_path: 拓扑图路径（.png/.jpg 等），由用户提供
        question: 针对这张图的具体问题；留空则输出完整的拓扑识读结果
    """
    from core import vision

    if not (image_path or "").strip():
        return "image_path 不能为空，请向用户索取拓扑图路径（可先用 list_local_images 查找）"

    try:
        return vision.describe_image(image_path.strip(), question=question,
                                     show_thinking=False)
    except FileNotFoundError as e:
        return f"{e}（可先用 list_local_images 查看可用图片）"
    except ValueError as e:
        return f"图片不可用：{e}"
    except RuntimeError as e:
        return f"识图失败：{e}"
    except Exception as e:  # noqa: BLE001  工具不抛异常
        return f"识图异常：{type(e).__name__}: {e}"
