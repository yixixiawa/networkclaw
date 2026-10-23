"""MCP 服务端测试：工具注册表、单工具文件结构、命名冲突检测、检索降级的用户可见文案。

不启动真正的 stdio 服务进程——直接 import 模块读它的工具清单/工具函数。

架构前提（2026-10 拆分后）：
    服务端文件（mcp_tools/*_server.py）只是**注册中心**：建 FastMCP 实例 + 装配工具。
    工具实现在 mcp_tools/tools/<工具名>.py，一个工具一个文件。
    因此「某工具存在」要查 tools/ 目录，不能再去服务端源码里找 `def xxx(`。

重点防四类回归：
  ① 两个服务端定义了同名工具（McpHub 按工具名路由，重名会串）；
  ② 单工具文件缺失或函数名与文件名不一致（注册中心 import 会炸）；
  ③ 服务端装配的工具数与文档清单不符（漏装配 = 模型看不见该工具）；
  ④ 检索降级时返回「知识库中没有相关内容」，让模型误以为是正常结论。
"""
import ast
import asyncio
import importlib
import inspect
from pathlib import Path

import pytest

MCP_DIR = Path(__file__).resolve().parent.parent / "mcp_tools"
TOOLS_DIR = MCP_DIR / "tools"

# 服务端标识 → (模块名, 期望装配的工具清单)，顺序与 docs/mcp_tools.md 一致
SERVER_TOOLS = {
    "knowledge": ("template_server", ["query_command_template", "search_knowledge"]),
    "device-serial": ("device_server", ["list_serial_ports", "classify_command",
                                        "exec_command", "recent_audit"]),
    "device-telnet": ("telnet_server", ["check_telnet", "exec_telnet_command"]),
    "device-manual": ("manual_server", ["list_device_manuals", "list_session_skills",
                                        "read_device_manual", "create_device_manual",
                                        "update_device_manual_section",
                                        "recent_device_history"]),
    "data-report": ("report_server", ["export_workflow_report", "workflow_report_overview",
                                       "list_report_sessions"]),
    "topology": ("topology_server", ["discover_topology", "load_discovered_topology",
                                      "topology_summary", "topology_mermaid"]),
    "vision": ("vision_server", ["vision_ready", "list_local_images",
                                  "analyze_topology_image", "capture_topology",
                                  "get_topology_snapshot"]),
}


# ---------------------------------------------------------------- 单工具文件结构

def _tool_files() -> list[Path]:
    """tools/ 下的工具文件（跳过 __init__ 与 _ 开头的公共支撑模块）。"""
    return sorted(p for p in TOOLS_DIR.glob("*.py") if not p.name.startswith("_"))


def _code_only(src: str) -> str:
    """剥掉 docstring 与注释，只留可执行代码（避免把说明文字误判成实现）。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_every_tool_has_its_own_file():
    """一个工具一个文件：每个 MCP 工具都能在 tools/ 找到同名文件。"""
    expected = {t for _, tools in SERVER_TOOLS.values() for t in tools}
    actual = {p.stem for p in _tool_files()}
    assert expected == actual, f"缺失 {expected - actual}，多余 {actual - expected}"


def test_tool_file_defines_function_of_same_name():
    """文件名 = 函数名。不一致会让注册中心的 import 直接炸。"""
    bad = []
    for fp in _tool_files():
        tree = ast.parse(fp.read_text(encoding="utf-8"))
        funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        if fp.stem not in funcs:
            bad.append(f"{fp.name}（定义了 {sorted(funcs)}）")
    assert not bad, f"文件名与函数名不一致：{bad}"


def test_tool_files_have_docstrings():
    """工具的 docstring 就是给模型看的描述，空着等于没告诉模型这工具能干什么。"""
    missing = []
    for fp in _tool_files():
        mod = importlib.import_module(f"mcp_tools.tools.{fp.stem}")
        fn = getattr(mod, fp.stem, None)
        if not (fn and (inspect.getdoc(fn) or "").strip()):
            missing.append(fp.name)
    assert not missing, f"缺少 docstring：{missing}"


def test_tool_files_are_not_decorated():
    """工具文件里不挂 @mcp.tool——装配是服务端注册中心的职责。

    这样工具函数可脱离 MCP 运行时被直接调用（测试/脚本/复用）。
    """
    decorated = []
    for fp in _tool_files():
        tree = ast.parse(fp.read_text(encoding="utf-8"))
        for n in tree.body:
            if isinstance(n, ast.FunctionDef) and n.decorator_list:
                names = [ast.unparse(d) for d in n.decorator_list]
                if any("mcp" in x or "tool" in x for x in names):
                    decorated.append(f"{fp.name}: {names}")
    assert not decorated, f"工具文件不应自行注册：{decorated}"


# ---------------------------------------------------------------- 服务端装配

@pytest.mark.parametrize("server", sorted(SERVER_TOOLS))
def test_server_registers_expected_tools(server):
    """每个服务端装配的工具必须与文档清单一致（漏装配 = 模型看不见该工具）。"""
    module_name, expected = SERVER_TOOLS[server]
    mod = importlib.import_module(f"mcp_tools.{module_name}")
    tools = asyncio.run(mod.mcp.list_tools())
    assert sorted(t.name for t in tools) == sorted(expected)


def test_total_tool_count_is_26():
    """总数回归：新增/删除工具时同步更新本断言与文档。"""
    total = 0
    for module_name, _ in SERVER_TOOLS.values():
        mod = importlib.import_module(f"mcp_tools.{module_name}")
        total += len(asyncio.run(mod.mcp.list_tools()))
    assert total == 26, f"工具总数变为 {total}，请同步 docs/mcp_tools.md 与本断言"


def test_no_duplicate_tool_names_across_servers():
    """关键回归：两个服务端不得定义同名工具（否则 McpHub 路由会串）。"""
    seen: dict[str, str] = {}
    dupes = []
    for server, (_, tools) in SERVER_TOOLS.items():
        for name in tools:
            if name in seen:
                dupes.append(f"{name}: {seen[name]} ↔ {server}")
            seen[name] = server
    assert not dupes, f"存在重名工具：{dupes}"


def test_server_files_contain_no_business_logic():
    """服务端文件应只剩注册职责：不得再出现 @mcp.tool 装饰器或实现细节。

    只检查**代码**（剥掉 docstring 与注释）——文档里描述 `audit(` / 日志路径
    是正常的说明文字，不该被当成残留实现。
    """
    offenders = []
    for _, (server_mod, _) in SERVER_TOOLS.items():
        src = (MCP_DIR / f"{server_mod}.py").read_text(encoding="utf-8")
        if "@mcp.tool" in src:
            offenders.append(f"{server_mod}.py 仍有 @mcp.tool 装饰器")

        code = _code_only(src)
        # 注册中心只调 mcp.tool(fn)，不该出现连接/审计这类实现细节
        for kw in ("open_telnet", "open_serial", "audit(", "write_text"):
            if kw in code:
                offenders.append(f"{server_mod}.py 残留实现细节：{kw}")
    assert not offenders, offenders


# ---------------------------------------------------------------- 工具行为

def test_search_knowledge_reports_degradation(monkeypatch):
    """检索降级时，工具返回值必须显式说明「不可用」，而不是「没有找到」。"""
    from core import rag
    from mcp_tools.tools import search_knowledge as sk

    monkeypatch.setattr(rag, "build_index", lambda *a, **k: 0)

    class Degraded:
        status, reason, chunks = "embed_failed", "连接被拒绝", []
        ok = False
        degraded = True

    monkeypatch.setattr(rag, "retrieve_ex", lambda q, n_results=3: Degraded())
    out = sk.search_knowledge("BGP 邻居起不来")
    assert "不可用" in out
    assert "不是「知识库中没有相关内容」" in out
    assert "不要凭记忆编造" in out


def test_search_knowledge_reports_no_match(monkeypatch):
    """确实没查到时，文案应当是「没有找到」而不是「不可用」。"""
    from core import rag
    from mcp_tools.tools import search_knowledge as sk

    monkeypatch.setattr(rag, "build_index", lambda *a, **k: 0)

    class NoMatch:
        status, reason, chunks = "no_match", "没有匹配片段", []
        ok = False
        degraded = False

    monkeypatch.setattr(rag, "retrieve_ex", lambda q, n_results=3: NoMatch())
    out = sk.search_knowledge("随便问问")
    assert "没有找到" in out
    assert "不可用" not in out


def test_search_knowledge_empty_query():
    from mcp_tools.tools import search_knowledge as sk
    assert sk.search_knowledge("   ") == "query 不能为空"


def test_mcp_client_detects_duplicate_names():
    """McpHub 的同名检测：两个服务端给同名工具时应能识别（防路由串台）。"""
    src = (MCP_DIR / "client.py").read_text(encoding="utf-8")
    assert "_load_tools" in src
    assert "重名" in src or "duplicate" in src.lower(), "client 里应有重名检测逻辑"
