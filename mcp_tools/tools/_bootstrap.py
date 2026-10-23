"""单工具模块的公共支撑：项目根路径引导 + 回显截断。

为什么不用装饰器而用普通函数：
    工具文件只写裸函数（不带 @mcp.tool），由服务端注册中心 `mcp.tool(fn)` 装配。
    好处是工具函数可以脱离 MCP 运行时被直接调用（测试、脚本、复用）。

导入约定：
    每个工具文件顶部先 `from mcp_tools.tools import _bootstrap`（为 sys.path 兜底），
    再导入 core。服务端被 MCP 客户端以「任意工作目录」拉起，没有这一步会
    `ModuleNotFoundError: core`。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 回显过长会挤爆模型上下文：统一在工具层截断（原始内容仍在运行日志里）
MAX_OUTPUT = 6000


def truncate(text: str, limit: int = MAX_OUTPUT,
             note: str = "可用 display ... | include 缩小范围") -> str:
    """截断过长回显，并在尾部说明共多少字、怎么缩小范围。"""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...（回显共 {len(text)} 字，已截断；{note}）"


def relpath(path: str) -> str:
    """把绝对路径转成项目内相对路径（给用户看更短）；失败时原样返回。"""
    if not path:
        return ""
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except (ValueError, OSError):
        return path
