"""MCP 工具 recent_device_history：查看某台设备最近的命令历史。

作用点：**回看本机做过什么**。历史由工具层自动记录（见 mcp_tools/tools/_archive.py），
模型无需手工维护，也不会漏记——这是复盘与 SFT 语料的原料。

设备身份的坑（2026-10 实测）：历史按设备名落目录，而模型常按「用户口头名」查询，
登记里却可能是 LSW1、或根本没绑定名字（退化成 `192.168.1.1_2001`）。直接用
查询词当目录名会查空，模型据此以为没做过、然后重做一遍。因此这里：
    1. 先用 device_registry.resolve_device 解析成唯一身份（支持 IP:端口/端口/COM）；
    2. 解析成功后把该设备的**全部别名目录**一起读（绑定名字之前的历史也能看到）；
    3. 解析失败或歧义时返回候选，绝不把别人的历史当这台设备的。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def recent_device_history(device: str, n: int = 10, session: str = "") -> str:
    """查看某台设备最近的命令历史（工具层自动记录，无需手工维护）。

    Args:
        device: 设备名或地址，例如 SW1 / LSW1 / 192.168.1.10:2003 / COM3
        n: 返回最近 n 条，默认 10
        session: 可选，显式查看**其他对话**里该设备的历史；留空表示当前对话
    """
    from core import device_manual, device_registry
    from mcp_tools.tools._manual_common import resolve, where

    r, err = resolve(device, session)
    if r is None:
        # 歧义：绝不猜（猜错就是把别的设备历史当成本设备经验）
        if device_registry.resolve_device(device, session).get("reason") == "ambiguous":
            return err
        empty = (f"会话「{session}」里设备「{device}」暂无命令历史"
                 if session else
                 f"当前会话里设备「{device}」暂无命令历史（执行过命令后会自动记录）")
        return f"{empty}\n{err}"

    name = r["name"]
    # 别名里只有合法目录名才可能是历史目录（host:port 会被 safe_name 拒掉）
    names = [name] + [a for a in r.get("aliases", []) if a != name]
    try:
        rows = device_manual.tail_history_merged(names, n, session)
    except device_manual.ManualError as e:
        return str(e)

    if not rows:
        msg = (f"会话「{session}」里设备「{name}」暂无命令历史"
               if session else
               f"当前会话里设备「{name}」暂无命令历史（执行过命令后会自动记录）")
        msg += (f"\n该设备已解析为 {name}"
                + (f"（地址 {r['host']}:{r['port']}）" if r.get("host") else "")
                + f"，别名：{', '.join(r['aliases'][:6])}"
                + f"。\n若历史在别的对话里，用 list_session_skills 查看哪个会话有该设备，"
                  f"再用 session 参数指定。")
        return msg

    head = f"{name} 在{where(session)}最近 {len(rows)} 条命令"
    if r.get("matched") not in ("name", "key"):
        head += f"（按「{device}」解析到 {name}）"
    lines = [head + "："]
    for rec in rows:
        # 兼容早期手工脚本写入的记录（只有 time/command/result/confirmed）
        if rec.get("executed"):
            flag = "已执行"
        elif "executed" in rec:
            flag = "未执行"
        else:
            flag = "—"
        lines.append(f"  [{rec.get('time')}] {rec.get('transport') or '—'} {flag} | "
                     f"{rec.get('command')}")
    return "\n".join(lines)
