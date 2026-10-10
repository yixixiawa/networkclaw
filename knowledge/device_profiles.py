"""设备型号基线画像：让「首次接触某台设备」不至于从零开始。

要解决的问题（冷启动空白）：
    `skills/<设备名>/SKILL.md` 是运行期逐步积累的产物。第 7 台设备第一次出现时
    它没有手册，而知识库里也没有「这个型号该怎么配」的具体条目——模型只能靠
    自身记忆，容易出现接口编号偏 1、忘了 undo shutdown 这类低级错误。

    于是这里维护一份**型号 → 基线要点**的静态画像：与具体设备实例无关，只描述
    「这个型号的通用套路与坑」。它在两个地方发挥作用：

      1. `create_device_manual` 建档时，把匹配到的画像要点填进手册的
         「注意事项」小节——手册从第一刻起就有可用内容，而不是三段占位符；
      2. `core/rag.py` 索引 `skills/` 时，这些要点随手册一起进知识库。

    画像只写**通用且稳定**的事实（端口编号、默认行为、命令视图）。
    任何随环境变化的内容（IP、VLAN 规划、拓扑角色）都不写在这里。

数据来源边界：
    本文件的内容来自华为产品文档与真机验证结论，属于「现行规则」；
    不包含任何具体项目的配置。新增型号时请只写可复现的通用事实。
"""
from __future__ import annotations

# key 用大写做匹配（子串匹配，因此 "S5700-28C-HI" 能命中 "S5700"）
PROFILES: dict[str, dict] = {
    "AR2220": {
        "kind": "router",
        "ports": "3 个千兆电口，**0 基编号**：GE0/0/0、GE0/0/1、GE0/0/2",
        "tips": [
            "GE 口配完 `ip address` 后要 `undo shutdown` 才会 up（默认可能 shutdown）",
            "第一个口是 GE0/0/0 而不是 GE0/0/1——接口编号偏 1 是最高频错误",
            "路由口不需要 `port link-type`（那是交换口的命令）",
        ],
    },
    "AR2200": {
        "kind": "router",
        "ports": "千兆电口，0 基编号（GE0/0/0 起）",
        "tips": [
            "GE 口需 `undo shutdown` 才 up",
            "接口编号 0 基，别写成 GE0/0/1 当第一个口",
        ],
    },
    "AR1200": {
        "kind": "router",
        "ports": "千兆电口，0 基编号",
        "tips": ["GE 口需 `undo shutdown` 才 up", "接口 0 基编号"],
    },
    "S5700": {
        "kind": "switch",
        "ports": "全千兆，**1 基编号**：GE0/0/1 起（S5700-LI 为二层，EI 支持三层）",
        "tips": [
            "第一个口是 GE0/0/1（与路由器相反）",
            "改接口类型前若已有 trunk/hybrid 配置，需先 `undo port link-type`，"
            "否则报 `Error: Please renew the default configuration`",
            "S5700-LI 不支持 `ip routing`，要三层功能必须是 EI 版本",
            "Trunk 口记得 `port trunk allow-pass vlan`，否则业务 VLAN 不通",
        ],
    },
    "S3700": {
        "kind": "switch",
        "ports": "百兆接入，1 基编号：Ethernet0/0/1 或 GE0/0/1",
        "tips": [
            "接口 1 基编号",
            "百兆口写作 `Ethernet0/0/x`，千兆口写作 `GigabitEthernet0/0/x`，不要混",
            "改接口类型前先 `undo port link-type`",
        ],
    },
    "S6700": {
        "kind": "switch",
        "ports": "万兆上行交换机，1 基编号",
        "tips": ["接口 1 基编号", "多用于汇聚，注意上行口 `port trunk allow-pass vlan`"],
    },
    "S7700": {
        "kind": "switch",
        "ports": "核心交换机，槽位式（如 GE1/0/1 表示 1 号槽），支持 CSS 集群",
        "tips": ["端口编号含槽位号（第 2 段是槽位）", "支持 CSS 集群，配置前先确认是否堆叠"],
    },
    "S12700": {
        "kind": "switch",
        "ports": "核心交换机，槽位式编号，支持 CSS 集群",
        "tips": ["端口编号含槽位号", "支持 CSS 集群"],
    },
    "NE40E": {
        "kind": "router",
        "ports": "运营商级路由器，槽位式编号",
        "tips": ["端口编号含槽位号（如 GE1/0/0）", "配置量级大，注意保存耗时"],
    },
    "USG": {
        "kind": "firewall",
        "ports": "华为防火墙，接口编号类似路由器（0 基）",
        "tips": [
            "防火墙默认区域策略是 deny，配完接口 IP 还要放行安全区域与策略",
            "接口需先加入安全区域（`firewall zone trust` + `add interface`）",
        ],
    },
}

# 型号匹配顺序：长 key 优先，避免 "AR22" 抢先匹配 "AR2220"
_ORDERED_KEYS = sorted(PROFILES, key=len, reverse=True)


def match(model: str) -> tuple[str, dict] | tuple[None, None]:
    """按型号名做子串匹配，返回 (命中的 key, 画像)；未命中返回 (None, None)。"""
    m = (model or "").upper()
    if not m:
        return None, None
    for key in _ORDERED_KEYS:
        if key in m:
            return key, PROFILES[key]
    return None, None


def baseline_tips(model: str) -> str:
    """把型号画像渲染成可写进手册的 Markdown 段落；未命中时返回空串。

    刻意返回空串而非"未知型号"占位——手册骨架里已有占位说明，
    再插一段空话只会稀释后面的真实内容。
    """
    key, prof = match(model)
    if not prof:
        return ""
    lines = [f"（型号基线：{key} — 来自 knowledge/device_profiles.py，通用事实，"
             f"具体以真机回显为准）", ""]
    if prof.get("ports"):
        lines.append(f"- 端口：{prof['ports']}")
    for tip in prof.get("tips", []):
        lines.append(f"- {tip}")
    return "\n".join(lines)


def device_kind(model: str) -> str:
    """返回设备大类（router/switch/firewall），未知时返回空串。"""
    _, prof = match(model)
    return (prof or {}).get("kind", "")


if __name__ == "__main__":
    for m in ("AR2220", "S5700-28C-HI", "S3700", "NE40E", "未知型号"):
        print(f"===== {m} =====")
        print(baseline_tips(m) or "（无匹配画像）")
