"""图像识别 MCP 服务端：让智能体看懂用户当前的网络拓扑。

工具列表：
1. vision_ready()
   - 检查当前 llama-server 是否已加载视觉投影文件（mmproj），识图前先自查
2. list_local_images(directory, limit)
   - 列出常见目录下最近的图片，用户只说「我截了张拓扑图」时用于定位文件
3. analyze_topology_image(image_path, question)
   - 识读拓扑图：设备清单（名称/型号/角色/IP）、连接关系（接口对接口）、网段与 VLAN、
     风险点（单点故障、环路）等结构化描述

前提：llama-server 必须以多模态方式启动，即主程序带 `--mmproj` 参数
      （core/llama_start.py 会自动探测 models/*mmproj*.gguf）。

运行方式（stdio，由 MCP 客户端拉起）：
    python mcp_tools/vision_server.py
"""
import sys
from pathlib import Path

# 保证从任意工作目录被 MCP 客户端拉起时都能导入 core 包
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastmcp import FastMCP  # noqa: E402

from core import vision  # noqa: E402

mcp = FastMCP("Network-Vision")


@mcp.tool
def vision_ready() -> str:
    """检查图像识别能力是否就绪（llama-server 是否已加载 mmproj 视觉投影文件）。"""
    status = vision.vision_status()
    mmproj = vision.find_mmproj()
    lines = [f"视觉能力：{'可用' if status['available'] else ('不可用' if status['available'] is False else '待确认')}"]
    lines.append(f"判据：{status['detail']}")
    lines.append(f"mmproj 文件：{mmproj if mmproj else '未找到'}")
    if not mmproj:
        lines.append(vision.mmproj_hint())
    return "\n".join(lines)


@mcp.tool
def list_local_images(directory: str = "", limit: int = 20) -> str:
    """列出可用的图片文件（用户提到截图/拓扑图但未给出完整路径时用）。

    Args:
        directory: 指定目录；留空则扫描桌面 / 下载 / 图片 / 文档与项目目录
        limit: 最多返回条数，默认 20
    """
    try:
        items = vision.list_local_images(directory or None, limit=max(1, limit))
    except Exception as e:
        return f"图片枚举失败：{type(e).__name__}: {e}"
    if not items:
        return "没有找到图片文件，请向用户索取拓扑图的完整路径。"
    lines = [f"找到 {len(items)} 张图片（按修改时间倒序）："]
    for it in items:
        lines.append(f"  - {it['path']}（{it['mb']} MB，{it['mtime']}）")
    return "\n".join(lines)


@mcp.tool
def analyze_topology_image(image_path: str, question: str = "") -> str:
    """识读网络拓扑图，输出设备清单、连接关系、IP/网段与风险点。

    Args:
        image_path: 拓扑图路径（.png/.jpg 等），由用户提供
        question: 针对这张图的具体问题；留空则输出完整的拓扑识读结果
    """
    if not (image_path or "").strip():
        return "image_path 不能为空，请向用户索取拓扑图路径（可先用 list_local_images 查找）"

    try:
        return vision.describe_image(image_path.strip(), question=question, show_thinking=False)
    except FileNotFoundError as e:
        return f"{e}（可先用 list_local_images 查看可用图片）"
    except ValueError as e:
        return f"图片不可用：{e}"
    except RuntimeError as e:
        return f"识图失败：{e}"
    except Exception as e:
        return f"识图异常：{type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
