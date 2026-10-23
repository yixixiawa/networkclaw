"""图像识别 MCP 服务端：让智能体看懂用户当前的网络拓扑。

本文件只做**注册中心**：建 FastMCP 实例，把 mcp_tools/tools/ 下单工具模块
装配进来。工具实现不在这里——一个工具一个文件（见 mcp_tools/tools/__init__.py）。

工具列表（实现文件 → 工具名）：
    tools/vision_ready.py           vision_ready()
        检查当前 llama-server 是否已加载视觉投影文件（mmproj），识图前先自查
    tools/list_local_images.py      list_local_images(directory, limit)
        列出常见目录下最近的图片，用户只说「我截了张拓扑图」时用于定位文件
    tools/analyze_topology_image.py analyze_topology_image(image_path, question)
        识读拓扑图：设备清单、连接关系、网段与 VLAN、风险点
    tools/capture_topology.py       capture_topology(keyword, force)
        实时查看当前拓扑：自动截取 eNSP / 虚拟机窗口后交给本地多模态模型识读
    tools/get_topology_snapshot.py  get_topology_snapshot()
        读取最近一次自动拓扑巡检的结论快照（不推理，瞬时返回）

前提：llama-server 必须以多模态方式启动，即主程序带 `--mmproj` 参数
      （core/llama_start.py 会自动探测 models/*mmproj*.gguf）。

运行方式（stdio，由 MCP 客户端拉起）：
    python mcp_tools/vision_server.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("Network-Vision")

# ---------------------------------------------------------------- 工具装配
# 一个工具一个文件：从 mcp_tools/tools/<工具名>.py 导入同名函数后注册。
from mcp_tools.tools.analyze_topology_image import analyze_topology_image  # noqa: E402
from mcp_tools.tools.capture_topology import capture_topology  # noqa: E402
from mcp_tools.tools.get_topology_snapshot import get_topology_snapshot  # noqa: E402
from mcp_tools.tools.list_local_images import list_local_images  # noqa: E402
from mcp_tools.tools.vision_ready import vision_ready  # noqa: E402

mcp.tool(vision_ready)
mcp.tool(list_local_images)
mcp.tool(analyze_topology_image)
mcp.tool(capture_topology)
mcp.tool(get_topology_snapshot)


if __name__ == "__main__":
    mcp.run(transport="stdio")
