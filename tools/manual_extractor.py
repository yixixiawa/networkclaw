"""阶段三脚手架：从官方手册文本粗提取命令模板候选，产出人工审核队列。

用法：
    python tools/manual_extractor.py knowledge/manuals/huawei_vrp.txt --vendor Huawei
    python tools/manual_extractor.py manual.txt --vendor Cisco --out knowledge/review_queue.csv

输入：导出为纯文本的官方手册片段（HTML/PDF 需先转换，TODO 见 parse 步骤）
输出：knowledge/review_queue.csv，字段与 command_templates.csv 对齐，
      另加 source 列记录来源文件。人工审核后并入 command_templates.csv。

注意：本脚手架只是粗提取 + 去重，intent 需人工补齐（见 docs/phase3_extraction_plan.md）。
"""
import argparse
import csv
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUT = BASE_DIR / "knowledge" / "review_queue.csv"
MAIN_CSV = BASE_DIR / "knowledge" / "command_templates.csv"

# 三家语法行的常见动词开头（启发式白名单，可按厂商扩充）
COMMAND_VERBS = [
    # 通用/VRP
    "system-view", "sysname", "display ", "undo ", "vlan ", "vlan batch",
    "interface ", "port ", "ip address", "ip route-static", "stelnet",
    "user-interface", "aaa", "local-user", "ssh ", "ntp-service", "clock ",
    "save", "description ",
    # Comware
    "line vty", "public-key local", "authorization-attribute",
    "ntp-service unicast",
    # Cisco
    "enable", "configure terminal", "hostname", "write ", "show ",
    "switchport ", "no switchport", "ip route ", "ip domain-name",
    "crypto key", "username ", "transport input", "login local",
    "ip ssh", "ntp server", "name ",
]

# 提示符/示例特征：出现这些的一般是交互示例，不是语法行
NOISE_PATTERNS = [
    r"^[<\[][\w\-.]+[>\]]",   # <Huawei> [SW1] 提示符开头
    r"\b[Yy]/[Nn]\b",          # y/n 交互
]

MODE_KEYWORDS = [
    ("系统视图", ["系统视图", "system view", "全局配置模式", "global configuration"]),
    ("接口视图", ["接口视图", "interface view", "接口配置模式", "interface configuration"]),
    ("用户视图", ["用户视图", "user view", "用户模式", "user EXEC"]),
    ("特权模式", ["特权模式", "privileged EXEC", "特权 EXEC"]),
    ("AAA视图", ["AAA视图", "AAA view"]),
    ("VTY视图", ["VTY", "user interface", "line configuration", "vty"]),
]

# device_type 启发式关键词（与 command_templates.csv 的取值保持一致：switch/router/both）
# 仅作候选提示：网络设备功能有交叉（如路由器的 VLAN 子接口），最终仍需人工复核。
SWITCH_HINTS = [
    "vlan batch", "vlan ", "undo vlan", "display vlan", "port link-type",
    "port default vlan", "port trunk", "port hybrid", "switchport mode",
    "switchport access vlan", "switchport trunk", "interface vlanif",
    "vlan-interface", "interface vlan", "spanning-tree", "stp ",
    "display stp", "mac-address-table",
]
ROUTER_HINTS = [
    "ip route-static", "ip route ", "ospf", "bgp", "isis", "redistribute",
    "import-route", "default-information", "default-route-advertise",
    "route-policy", "filter-policy", "acl ", "acl number", "acl basic",
    "acl advance", "packet-filter", "traffic-filter", "ip access-group",
    "radius", "aaa", "authorization", "domain ", "nat ", "interface tunnel",
]
BOTH_HINTS = [
    "sysname", "hostname", "save", "write ", "display current",
    "display version", "ssh", "stelnet", "rsa", "public-key",
    "user-interface", "line vty", "local-user", "username", "ntp",
    "clock ", "quit", "undo info-center",
]


def guess_device_type(command: str, context: str = "") -> str:
    """启发式推断命令适用的设备类型：switch / router / both，无法判断时返回 ""。

    判断顺序：命令关键词（最具体）→ 手册上下文里明说的设备类型 → 留空待人工填。
    """
    cmd = command.lower()
    for kw in SWITCH_HINTS:
        if kw in cmd:
            return "switch"
    for kw in ROUTER_HINTS:
        if kw in cmd:
            return "router"
    for kw in BOTH_HINTS:
        if kw in cmd:
            return "both"

    # 手册正文常写明「在路由器上执行」之类，作为兜底线索
    ctx = context or ""
    has_router = "路由器" in ctx or "router" in ctx.lower()
    has_switch = "交换机" in ctx or "switch" in ctx.lower()
    if has_router and not has_switch:
        return "router"
    if has_switch and not has_router:
        return "switch"
    return ""  # 无法判断：留空，提示人工填写


def looks_like_command(line: str) -> bool:
    """启发式判断一行文本是否是命令语法行"""
    s = line.strip()
    if not s or len(s) > 120:
        return False
    if any(re.search(p, s) for p in NOISE_PATTERNS):
        return False
    lower = s.lower()
    return any(lower.startswith(v) or lower == v.strip() for v in COMMAND_VERBS)


def guess_mode(context_lines: list[str]) -> str:
    """根据命令周边文本猜测配置视图（TODO: 按实际文档结构精修）"""
    ctx = " ".join(context_lines).lower()
    for mode, keywords in MODE_KEYWORDS:
        if any(k.lower() in ctx for k in keywords):
            return mode
    return ""


def extract(text: str, device_type: str = "") -> list[dict]:
    """粗提取候选条目。TODO: 针对具体 HTML/PDF 解析结果替换为结构化解析。

    device_type 显式传入时统一使用该值；否则按命令关键词启发式推断，
    推断不出则留空，等待人工在 review_queue.csv 中补齐。
    """
    lines = text.splitlines()
    candidates = []
    for i, line in enumerate(lines):
        if not looks_like_command(line):
            continue
        command = line.strip()
        # 归一化去重
        key = re.sub(r"\s+", " ", command.lower())
        if any(c["command"].lower() == key for c in candidates):
            continue
        context = " ".join(lines[max(0, i - 3):i])
        candidates.append({
            "vendor": "",           # 写出时统一填
            "device_type": device_type or guess_device_type(command, context),
            "category": "",         # 人工补
            "intent": "",           # 人工补（或用 LLM 辅助生成后审核）
            "command": command,
            "mode": guess_mode(lines[max(0, i - 3):i]),
            "note": "",
        })
    return candidates


def load_existing_keys() -> set[str]:
    """主表已有的命令（归一化后），用于只保留新增"""
    keys = set()
    if MAIN_CSV.exists():
        with open(MAIN_CSV, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                keys.add(re.sub(r"\s+", " ", (row.get("command") or "").lower()))
    return keys


def main():
    parser = argparse.ArgumentParser(description="手册命令模板粗提取（阶段三脚手架）")
    parser.add_argument("manual", help="手册纯文本文件路径")
    parser.add_argument("--vendor", required=True, choices=["Huawei", "H3C", "Cisco"])
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="审核队列输出路径")
    parser.add_argument("--device-type", default="", dest="device_type",
                        choices=["", "switch", "router", "both"],
                        help="强制指定设备类型；默认按命令关键词自动推断")
    args = parser.parse_args()

    text = Path(args.manual).read_text(encoding="utf-8", errors="ignore")
    candidates = extract(text, device_type=args.device_type)

    existing = load_existing_keys()
    fresh = [c for c in candidates if re.sub(r"\s+", " ", c["command"].lower()) not in existing]
    for c in fresh:
        c["vendor"] = args.vendor
        c["source"] = Path(args.manual).name

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = out_path.exists()
    with open(out_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["vendor", "device_type", "category", "intent", "command", "mode", "note", "source"],
        )
        if not file_exists:
            writer.writeheader()
        writer.writerows(fresh)

    blank_dtype = sum(1 for c in fresh if not c["device_type"])
    print(f"共提取候选 {len(candidates)} 条，其中新增 {len(fresh)} 条已追加到 {out_path}")
    if blank_dtype:
        print(f"其中 {blank_dtype} 条 device_type 无法自动推断（已留空），需人工填写")
    print("请在 review_queue.csv 中复核 device_type，并补齐 category / intent 后再并入 command_templates.csv")


if __name__ == "__main__":
    main()
