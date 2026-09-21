"""命令安全网关：设备命令的风险分级与执行裁决。

背景（为什么必须有这一层）：
    网络设备命令不可逆性极强——`undo` / `shutdown` / `reset saved-configuration` 一执行
    就可能断网、清配置。让大模型自主决定执行哪些命令，一旦理解偏差就是生产事故。
    因此所有设备执行通道（串口 / Telnet）都必须先过这里。

三级策略：
    allow    只读类命令，直接执行
             display / show / ping / tracert（含 dir / more 等纯查看命令）
    confirm  配置类命令，必须经用户确认后才执行
             sysname / vlan / interface 等；**未匹配任何规则的命令默认归入此类**（保守兜底）
    block    破坏性命令，直接拦截，任何情况下都不执行
             undo / shutdown / delete / reset / reboot 等

配套能力：
    - 多命令拆分：`a ; b` 或换行分隔时逐条裁决，任一条被拦截则整体拒绝
    - `undo` / `no` 前缀识别：Huawei/H3C 的 `undo x` 与 Cisco 的 `no x` 一律视为高危
    - 视图切换类命令（system-view / configure terminal）归入 confirm：它本身不破坏配置，
      但会把会话留在配置视图，后续命令风险随之升高
    - 审计：每一次裁决都追加到 logs/command_audit.log，事后可追溯是谁在什么通道下发了什么

被 mcp_tools/device_server.py（串口）与 mcp_tools/telnet_server.py（Telnet）共用。
"""
import datetime
import json
import re

from core.paths import BASE_DIR

AUDIT_LOG = BASE_DIR / "logs" / "command_audit.log"

# ---------------------------------------------------------------- 分级常量
ALLOW = "allow"
CONFIRM = "confirm"
BLOCK = "block"

LEVEL_CN = {ALLOW: "允许", CONFIRM: "需确认", BLOCK: "已拦截"}

# 一级关键字 → 等级。查表时取命令的第一个词（跳过 undo/no 前缀后）
ALLOW_KEYWORDS = {
    # 用户明确要求放行的四类
    "display", "show", "ping", "tracert", "traceroute",
    # 其余纯查看/回显类命令，风险与上面同级
    "dir", "more", "help", "cat", "less", "type",
    "terminal", "screen-length", "quit", "return",
}

BLOCK_KEYWORDS = {
    # 撤销类：任何 undo / no 前缀都会命中下面 _strip_negation 的处理
    "undo", "no", "negate",
    # 危险性操作
    "shutdown", "delete", "reset", "reboot", "reload", "erase", "format",
    "factory-reset", "clean", "clear", "purge", "kill", "uninstall",
    "startup", "save",  # save/write 会覆写启动配置，涉及持久化，按高危处理
    "write", "copy", "tftp", "ftp", "startup-configuration", "saved-configuration",
}

# 配置类关键字：命中则给出「为什么需要确认」的具体说明
CONFIG_KEYWORDS = {
    "sysname": "修改设备名称",
    "hostname": "修改设备名称",
    "vlan": "修改 VLAN 配置",
    "interface": "进入/修改接口配置",
    "port": "修改端口配置",
    "ip": "修改 IP / 路由 / 地址配置",
    "ipv6": "修改 IPv6 配置",
    "ospf": "修改 OSPF 路由进程",
    "isis": "修改 IS-IS 路由进程",
    "bgp": "修改 BGP 路由进程",
    "rip": "修改 RIP 路由进程",
    "static": "修改静态路由",
    "acl": "修改 ACL 访问控制列表",
    "aaa": "修改 AAA 认证配置",
    "radius": "修改 RADIUS 服务器配置",
    "local-user": "修改本地用户",
    "user": "修改用户配置",
    "ssh": "修改 SSH 服务配置",
    "stelnet": "修改 Telnet/SSH 登录配置",
    "telnet": "修改 Telnet 服务配置",
    "ntp": "修改时间同步配置",
    "snmp": "修改 SNMP 配置",
    "stp": "修改生成树配置",
    "link-aggregation": "修改链路聚合",
    "eth-trunk": "修改 Eth-Trunk 聚合口",
    "route": "修改路由配置",
    "system-view": "进入系统视图（后续命令风险升高）",
    "configure": "进入全局配置视图（后续命令风险升高）",
    "config": "进入/修改配置",
    "enable": "提升到特权模式",
    "clock": "修改设备时间",
    "domain": "修改域名配置",
    "save": "保存配置到设备",
}

# 视图切换命令：确认类，但不会立即改变配置
VIEW_KEYWORDS = {"system-view", "configure", "disable", "quit", "return", "end", "exit"}

# ---------------------------------------------------------------- 命令切分


def split_commands(command: str) -> list[str]:
    """把一行拆成多条命令（`;` 或换行分隔），并去掉输出过滤管道。"""
    parts = []
    for raw in re.split(r"[;\r\n]+", command or ""):
        # `display current-configuration | include ssh` 里的管道只影响回显，不影响风险
        head = raw.split("|")[0]
        head = re.sub(r"\s+", " ", head).strip()
        if head:
            parts.append(head)
    return parts


def _strip_negation(words: list[str]) -> tuple[list[str], bool]:
    """识别 undo / no 前缀，返回（去掉前缀后的词表, 是否命中否定前缀）"""
    if words and words[0].lower() in ("undo", "no", "negate"):
        return words[1:], True
    return words, False


def _first_keyword(words: list[str]) -> str:
    """取命令的首关键字；跳过 `system-view` 之后的视图限定词（如 vlan 10 中的 vlan）"""
    return words[0].lower().strip() if words else ""


# ---------------------------------------------------------------- 单条裁决


def classify_one(command: str) -> dict:
    """对单条命令做分级，返回 {"level", "keyword", "reason"}"""
    words = command.strip().split()
    if not words:
        return {"level": ALLOW, "keyword": "", "reason": "空命令，无需执行"}

    keyword = _first_keyword(words)
    stripped, negated = _strip_negation(words)

    # 1) 否定前缀：undo x / no x 一律按破坏性处理（Huawei undo、Cisco no）
    if negated:
        target = _first_keyword(stripped) or "配置"
        return {
            "level": BLOCK,
            "keyword": keyword,
            "reason": f"`{words[0]}` 撤销前缀会删除现有配置（目标：{target}），属于不可逆操作",
        }

    # 2) 显式高危关键字
    if keyword in BLOCK_KEYWORDS:
        return {
            "level": BLOCK,
            "keyword": keyword,
            "reason": f"`{keyword}` 属于破坏性/持久化操作，可能导致断网或配置丢失",
        }

    # 3) 只读类
    if keyword in ALLOW_KEYWORDS:
        return {"level": ALLOW, "keyword": keyword, "reason": f"`{keyword}` 为只读查看类命令"}

    # 4) 配置类：命中配置关键字则给出具体说明
    for w in [keyword] + [x.lower() for x in stripped[:2]]:
        if w in CONFIG_KEYWORDS:
            return {
                "level": CONFIRM,
                "keyword": keyword,
                "reason": f"`{w}` 会改变设备配置（{CONFIG_KEYWORDS[w]}），需要用户确认",
            }

    # 5) 兜底：未知命令一律按需确认处理（保守原则）
    return {
        "level": CONFIRM,
        "keyword": keyword,
        "reason": f"`{keyword}` 不在放行清单内，按默认策略视为配置类命令，需要用户确认",
    }


def classify(command: str) -> dict:
    """对（可能含多条子命令的）命令做整体分级。

    返回：
        {
          "level": "allow" | "confirm" | "block",   # 取所有子命令中最高风险等级
          "parts": [{"command", "level", "keyword", "reason"}, ...],
          "reason": 汇总说明,
          "text":   可直接回给模型/用户的说明文本,
        }
    """
    parts = split_commands(command)
    if not parts:
        return {
            "level": ALLOW, "parts": [], "reason": "空命令",
            "text": "命令为空，没有需要执行的内容。",
        }

    details = []
    for p in parts:
        d = classify_one(p)
        d["command"] = p
        details.append(d)

    order = {ALLOW: 0, CONFIRM: 1, BLOCK: 2}
    level = max((d["level"] for d in details), key=lambda x: order[x])

    blocked = [d for d in details if d["level"] == BLOCK]
    confirm = [d for d in details if d["level"] == CONFIRM]
    if blocked:
        reason = "；".join(f"{d['command']}：{d['reason']}" for d in blocked)
    elif confirm:
        reason = "；".join(f"{d['command']}：{d['reason']}" for d in confirm)
    else:
        reason = "；".join(d["reason"] for d in details)

    return {
        "level": level,
        "parts": details,
        "reason": reason,
        "text": _format_report(command, level, details),
    }


def _format_report(command: str, level: str, details: list[dict]) -> str:
    """生成给模型看的裁决说明（含下一步该怎么做）"""
    head = f"命令分级结果：{LEVEL_CN[level]}"
    body = [f"命令：{command}"]
    for d in details:
        body.append(f"  - [{LEVEL_CN[d['level']]}] {d['command']} —— {d['reason']}")

    if level == BLOCK:
        tail = ("\n该命令属于破坏性操作，工具层已拒绝执行。"
                "请勿尝试绕过；如确需执行，请由人工在设备上完成。")
    elif level == CONFIRM:
        tail = ("\n该命令会改变设备配置。请先把命令内容与影响说明给用户，"
                "得到明确同意后带 confirm=true 重新调用本工具。")
    else:
        tail = "\n只读命令，可直接执行。"
    return head + "\n" + "\n".join(body) + tail


def check(command: str, confirmed: bool = False) -> tuple[bool, str, dict]:
    """执行前的统一裁决入口。

    Args:
        command: 待执行命令
        confirmed: 调用方（模型）是否已获得用户明确同意

    Returns:
        (是否放行, 回给模型/用户的说明文本, 分级详情)
    """
    decision = classify(command)

    if decision["level"] == BLOCK:
        return False, decision["text"], decision
    if decision["level"] == CONFIRM and not confirmed:
        return False, decision["text"], decision
    if decision["level"] == CONFIRM and confirmed:
        return True, f"（用户已确认）{decision['text']}", decision
    return True, decision["text"], decision


# ---------------------------------------------------------------- 审计


def audit(command: str, decision: dict, *, transport: str, target: str,
          confirmed: bool, executed: bool, extra: str = "") -> None:
    """把一次裁决写入审计日志（追加，永不覆盖）。失败不影响主流程。"""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "time": datetime.datetime.now().isoformat(timespec="seconds"),
            "transport": transport,          # serial / telnet
            "target": target,                # COM3 / 192.168.1.1:23
            "command": command,
            "level": decision.get("level"),
            "confirmed": confirmed,
            "executed": executed,
            "reason": decision.get("reason", ""),
            "extra": extra,
        }
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 审计失败绝不能阻断（或污染）真正的执行结果


def audit_tail(n: int = 20) -> list[dict]:
    """读取最近 n 条审计记录（供自检 / 命令行查看）"""
    if not AUDIT_LOG.exists():
        return []
    lines = AUDIT_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


if __name__ == "__main__":
    # 自检：打印各类命令的裁决结果
    samples = [
        "display current-configuration",
        "show ip route | include 192.168.1.0",
        "ping 8.8.8.8",
        "tracert 114.114.114.114",
        "sysname SW-Core-01",
        "vlan 100",
        "interface GigabitEthernet0/0/1",
        "undo vlan 100",
        "no ip route 0.0.0.0 0.0.0.0 10.0.0.1",
        "shutdown",
        "reset saved-configuration",
        "reboot",
        "display version ; reboot",
    ]
    for s in samples:
        d = classify(s)
        print(f"[{LEVEL_CN[d['level']]:>4}] {s}\n        {d['reason']}")
