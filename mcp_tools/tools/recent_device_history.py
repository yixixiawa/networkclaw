"""MCP 工具 recent_device_history：查看某台设备最近的命令历史。

作用点：**回看本机做过什么**。历史由工具层自动记录（见 mcp_tools/tools/_archive.py），
模型无需手工维护，也不会漏记——这是复盘与 SFT 语料的原料。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def recent_device_history(device: str, n: int = 10, session: str = "") -> str:
    """查看某台设备最近的命令历史（工具层自动记录，无需手工维护）。

    Args:
        device: 设备名，例如 SW1
        n: 返回最近 n 条，默认 10
        session: 可选，显式查看**其他对话**里该设备的历史；留空表示当前对话
    """
    from core import device_manual
    from mcp_tools.tools._manual_common import where

    try:
        rows = device_manual.tail_history(device, n, session)
    except device_manual.ManualError as e:
        return str(e)
    if not rows:
        if session:
            return f"会话「{session}」里设备「{device}」暂无命令历史"
        return f"当前会话里设备「{device}」暂无命令历史（执行过命令后会自动记录）"

    lines = [f"{device} 在{where(session)}最近 {len(rows)} 条命令："]
    for r in rows:
        # 兼容早期手工脚本写入的记录（只有 time/command/result/confirmed）
        if r.get("executed"):
            flag = "已执行"
        elif "executed" in r:
            flag = "未执行"
        else:
            flag = "—"
        lines.append(f"  [{r.get('time')}] {r.get('transport') or '—'} {flag} | {r.get('command')}")
    return "\n".join(lines)
