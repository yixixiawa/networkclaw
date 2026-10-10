"""设备报错 → 标准解法提示。

背景：本地 9B 模型在 eNSP 实验里最大的失败模式不是"不会配"，而是
**看不懂设备的英文报错，于是原地重发同一条命令直到轮次耗尽**。
实测 `Error: Please renew the default configuration` 一个错就能让模型空转 8 轮。

这里的规则是把厂商报错翻译成"下一步该敲什么"，随工具回显一起回给模型，
相当于给模型外挂一小块可维护的排错知识库。命中即追加，不命中不打扰。

规则来源：华为 S 系列（eNSP S5700）实测回显 + 官方配置指南。
新增规则时保持 (关键词, 提示) 的形式即可。
"""
from __future__ import annotations

# (报错特征串, 给模型的修正指引)
_RULES: list[tuple[str, str]] = [
    (
        "renew the default configuration",
        "接口上还残留旧类型配置。清理必须按 allow-pass → pvid → link-type 的顺序："
        "`undo port trunk allow-pass vlan 10 20 30` → `undo port trunk pvid vlan` → "
        "`port link-type access`。只发 `undo port link-type` 是清不掉的。",
    ),
    (
        "unrecognized command",
        "命令或视图不对：确认当前在正确视图（接口配置要先 `interface X`），"
        "且该型号支持这条命令。可先用 `display current-configuration` 确认。",
    ),
    (
        "incomplete command",
        "命令缺少必填参数（例如 vlan id、接口编号）。补齐参数再发。",
    ),
    (
        "wrong parameter",
        "参数取值非法：检查 VLAN ID 范围（1-4094）、接口编号是否存在、"
        "接口类型与后续命令是否匹配（access 口不能配 trunk 命令）。",
    ),
    (
        "the vlan does not exist",
        "VLAN 不存在，先 `vlan batch <id>` 创建再引用。",
    ),
    (
        "error: too many parameters",
        "参数过多或命令串接时被拆错。拆成单条命令逐条下发。",
    ),
    (
        "is not in the allowed vlan list",
        "该 VLAN 未在放行列表里。trunk 口要先 `port trunk allow-pass vlan <id>`。",
    ),
    (
        "conflict",
        "接口上已有互斥配置（例如同一口既配 access 又配 trunk 属性）。"
        "先按 allow-pass → pvid → link-type 顺序清干净再配。",
    ),
]


def hints_for(text: str, max_hits: int = 2) -> list[str]:
    """从设备回显里找出已知报错，返回对应的中文修正指引。"""
    if not text:
        return []
    low = text.lower()
    out: list[str] = []
    for key, tip in _RULES:
        if key in low and tip not in out:
            out.append(tip)
        if len(out) >= max_hits:
            break
    return out


def format_hints(text: str) -> str:
    """把命中提示拼成可直接塞进工具回显的一段话；没命中返回空串。"""
    tips = hints_for(text)
    if not tips:
        return ""
    # 别用 emoji / ⚠：Windows 控制台默认 GBK，编码不了就直接 UnicodeEncodeError
    body = "\n".join(f"  - {t}" for t in tips)
    return f"\n\n[排错指引] 按此修改命令，不要原样重发：\n{body}"


if __name__ == "__main__":
    demo = ("Error: Please renew the default configuration.\n"
            "Error: The VLAN does not exist.")
    print(format_hints(demo))
