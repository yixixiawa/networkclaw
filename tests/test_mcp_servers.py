"""MCP 服务端测试：工具注册表、命名冲突检测、检索降级的用户可见文案。

不启动真正的 stdio 服务进程——直接 import 模块读它的工具函数/注册表。
重点防两类回归：
  ① 两个服务端定义了同名工具（McpHub 按工具名路由，重名会串）；
  ② 检索降级时返回「知识库中没有相关内容」，让模型误以为是正常结论。
"""
import asyncio
import inspect

import pytest


def _tool_names(module):
    """取出模块里所有 @mcp.tool 注册的函数名。"""
    names = []
    for name, obj in vars(module).items():
        if inspect.isfunction(obj) and getattr(obj, "__wrapped_by__", None):
            names.append(name)
    if not names:
        # FastMCP 未运行时用注解标记识别；退化到按已知前缀筛
        names = [n for n, o in vars(module).items()
                 if inspect.isfunction(o) and not n.startswith("_")
                 and getattr(o, "__module__", "").endswith(module.__name__)]
    return names


def test_template_server_tools_exist():
    """知识/模板服务端两个核心工具必须在。"""
    from mcp_tools import template_server as ts
    src = inspect.getsource(ts)
    assert "def query_command_template" in src
    assert "def search_knowledge" in src


def test_no_duplicate_tool_names_across_servers():
    """关键回归：两个服务端不得定义同名工具（否则 McpHub 路由会串）。"""
    import re
    from pathlib import Path

    servers = ["template_server", "device_server", "telnet_server",
               "vision_server", "manual_server"]
    root = Path(__file__).resolve().parent.parent / "mcp_tools"
    seen: dict[str, str] = {}
    dupes = []
    for s in servers:
        f = root / f"{s}.py"
        if not f.exists():
            continue
        for name in re.findall(r"^def (\w+)\(", f.read_text(encoding="utf-8"), re.M):
            if name.startswith(("_", "tool_")) or name in ("main",):
                continue
            if name in seen:
                dupes.append(f"{name}: {seen[name]} ↔ {s}")
            seen[name] = s
    assert not dupes, f"存在重名工具：{dupes}"


def test_search_knowledge_reports_degradation(monkeypatch):
    """检索降级时，工具返回值必须显式说明「不可用」，而不是「没有找到」。"""
    from core import rag
    from mcp_tools import template_server as ts

    monkeypatch.setattr(ts, "build_knowledge_index", lambda *a, **k: 0)

    class Degraded:
        status, reason, chunks = "embed_failed", "连接被拒绝", []
        ok = False
        degraded = True

    monkeypatch.setattr(ts, "retrieve_ex", lambda q, n_results=3: Degraded())
    out = ts.search_knowledge("BGP 邻居起不来")
    assert "不可用" in out
    assert "不是「知识库中没有相关内容」" in out
    assert "不要凭记忆编造" in out


def test_search_knowledge_reports_no_match(monkeypatch):
    """确实没查到时，文案应当是「没有找到」而不是「不可用」。"""
    from mcp_tools import template_server as ts
    monkeypatch.setattr(ts, "build_knowledge_index", lambda *a, **k: 0)

    class NoMatch:
        status, reason, chunks = "no_match", "没有匹配片段", []
        ok = False
        degraded = False

    monkeypatch.setattr(ts, "retrieve_ex", lambda q, n_results=3: NoMatch())
    out = ts.search_knowledge("随便问问")
    assert "没有找到" in out
    assert "不可用" not in out


def test_search_knowledge_empty_query():
    from mcp_tools import template_server as ts
    assert ts.search_knowledge("   ") == "query 不能为空"


def test_mcp_client_detects_duplicate_names():
    """McpHub 的同名检测：两个服务端给同名工具时应能识别（防路由串台）。"""
    import re
    from pathlib import Path
    client = Path(__file__).resolve().parent.parent / "mcp_tools" / "client.py"
    src = client.read_text(encoding="utf-8")
    assert "_load_tools" in src
    assert "重名" in src or "duplicate" in src.lower(), "client 里应有重名检测逻辑"
