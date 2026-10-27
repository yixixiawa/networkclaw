"""实验环境快照：把 VM 里 eNSP 全部设备的「实际配置」拉回来，产出可喂给模型的紧凑摘要。

为什么要单独写脚本，而不是让模型逐台调 exec_telnet_command：
    21 台设备 × 每台 2~3 条命令，9B 模型一轮 30s 起，光采集就要十几分钟且容易在
    上下文里被截断。采集是**确定性的**（只读 display），交给工具层并发做；
    模型负责的是「看不懂的语义部分」——对照设计要求判断配置是否落地。
    分工写在 prompt 里，模型不需要知道采集细节。

产物：
    data/lab_reports/current_<ts>/<port>_<name>.cfg   每台设备的原始配置（只读，本地留档）
    data/lab_reports/current_<ts>/digest.json         结构化摘要
    data/lab_reports/current_<ts>/digest.txt          紧凑文本摘要（喂模型用）

用法：
    python tools/lab_snapshot.py                 # 默认 LAB_HOST + 2000-2020
    python tools/lab_snapshot.py --ports 2000-2005
    python tools/lab_snapshot.py --host 192.168.183.137
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.device_conn import TelnetSession  # noqa: E402

HOST = os.environ.get("LAB_HOST", "192.168.183.137")

# ---------------------------------------------------------------- 配置特征提取

# 每条特征 = (键, 正则, 说明)。只做「有没有 / 有几个 / 举几个例子」，不做语义判断
FEATURES: list[tuple[str, str]] = [
    ("sysname", r"^sysname\s+(\S+)"),
    ("ipv4_iface", r"^\s*ip address\s+(\S+\s+\S+)"),
    ("ipv6_iface", r"^\s*ipv6 enable|^\s*ipv6 address\s+(\S+)"),
    ("vlanif", r"^interface\s+Vlanif(\d+)"),
    ("eth_trunk", r"^interface\s+Eth-Trunk(\d+)"),
    ("trunk_port", r"^\s*port link-type\s+trunk"),
    ("access_port", r"^\s*port link-type\s+access"),
    ("vlan_batch", r"^\s*vlan batch\s+(.+)"),
    ("ospf", r"^ospf\s+(\d+)"),
    ("ospf6", r"^ospfv3\s+(\d+)"),
    ("bgp", r"^bgp\s+(\d+)"),
    ("isis", r"^isis\s+(\d+)"),
    ("static_route", r"^ip route-static\s+(\S+)"),
    ("static_route_v6", r"^ipv6 route-static\s+(\S+)"),
    ("vrrp", r"^\s*vrrp vrid\s+(\d+)"),
    ("ipsec", r"^ipsec\s+proposal|^ike\s+proposal|^ipsec\s+policy"),
    ("dsvpn", r"^dsvpn|^interface\s+Tunnel"),
    ("gre_tunnel", r"^\s*tunnel-protocol\s+(\S+)"),
    ("acl", r"^acl\s+(?:number\s+)?(\d+|name\s+\S+)"),
    ("nat", r"^\s*nat\s+(\S+)|^nat\s+(\S+)"),
    ("firewall_zone", r"^firewall\s+zone\s+(\S+)|^security-zone\s+name\s+(\S+)"),
    ("security_policy", r"^security-policy|^\s*rule\s+name\s+(\S+)"),
    ("dhcp_pool", r"^ip pool\s+(\S+)"),
    ("dhcpv6_pool", r"^dhcpv6 pool\s+(\S+)"),
    ("telnet", r"^\s*telnet\s+server\s+enable|^\s*protocol inbound"),
    ("snmp", r"^snmp-agent"),
    ("aaa", r"^aaa\b"),
    ("stp", r"^\s*stp\s+(\S+)"),
    ("lldp", r"^\s*lldp\s+enable|^lldp enable"),
    ("user_interface", r"^user-interface\s+(\S+\s*\S*)"),
]

_COMPILED = [(k, re.compile(p, re.M)) for k, p in FEATURES]


def merge_multiline(cfg: str) -> str:
    """华为配置里长行被折成 `\n` 续行（缩进的多行），合并回一行便于正则匹配。"""
    out: list[str] = []
    for line in cfg.splitlines():
        if line.startswith(" ") and out and not line.strip().startswith(("description", "#")):
            out[-1] = out[-1] + " " + line.strip()
        else:
            out.append(line)
    return "\n".join(out)


def classify_role(model: str, cfg: str) -> str:
    """粗判设备角色（只作提示，最终判断交给模型）"""
    m = (model or "").upper()
    if "USG" in m or "SRG" in m or "FIREWALL" in m:
        return "防火墙/安全网关"
    if re.search(r"^interface\s+Vlanif", cfg, re.M) and re.search(r"^\s*ip address", cfg, re.M):
        if re.search(r"^(ospf|bgp|isis)\s", cfg, re.M):
            return "三层交换机(核心/汇聚)"
    if m.startswith("AR") or "AR" in m[:6] or "ROUTER" in m:
        return "路由器"
    if "S5" in m or "S6" in m or "S3" in m or "S2" in m or "S1" in m:
        return "二层交换机"
    return "未知"


def extract(cfg: str, model: str, port: int, sysname: str) -> dict:
    merged = merge_multiline(cfg)
    feats: dict[str, list[str]] = {}
    for key, rx in _COMPILED:
        hits = [next((g for g in m.groups() if g), "") for m in rx.finditer(merged)]
        hits = [h.strip() for h in hits if h is not None]
        if hits:
            feats[key] = hits
    return {
        "port": port,
        "sysname": sysname,
        "model": model,
        "role_guess": classify_role(model, merged),
        "features": feats,
        "config_lines": len(cfg.splitlines()),
    }


def summarize(d: dict) -> str:
    """把一台设备压成 2~5 行文本"""
    f = d["features"]

    def take(key: str, n: int = 4) -> str:
        vals = f.get(key) or []
        if not vals:
            return "-"
        head = ", ".join(str(v) for v in vals[:n])
        return head + (f" …共{len(vals)}" if len(vals) > n else "")

    lines = [f"[{d['port']}] {d['sysname'] or '(无sysname)'} | {d['model'] or '?'} | {d['role_guess']}"]
    row = {
        "IPv4接口": take("ipv4_iface"),
        "IPv6": take("ipv6_iface"),
        "Vlanif": take("vlanif"),
        "Eth-Trunk": take("eth_trunk"),
        "VLAN": take("vlan_batch"),
        "OSPF": take("ospf"),
        "OSPFv3": take("ospf6"),
        "BGP": take("bgp"),
        "静态路由": take("static_route", 3),
        "IPv6路由": take("static_route_v6", 3),
        "VRRP": take("vrrp"),
        "IPsec/IKE": take("ipsec"),
        "DSVPN/Tunnel": take("dsvpn"),
        "ACL": take("acl"),
        "NAT": take("nat"),
        "安全域": take("firewall_zone"),
        "安全策略": take("security_policy"),
        "DHCP": take("dhcp_pool"),
        "DHCPv6": take("dhcpv6_pool"),
        "LLDP": take("lldp"),
    }
    parts = [f"{k}={v}" for k, v in row.items() if v != "-"]
    if parts:
        lines.append("    " + "; ".join(parts))
    if not parts:
        lines.append("    （配置为空/仅有默认配置）")
    return "\n".join(lines)


def detect_model(ver: str, cfg: str) -> str:
    """从 `display version` 判型号。

    eNSP 里三种典型回显（2026-10-23 实测）：
      · `Quidway S5700-28C-HI Routing Switch uptime is ...`   → 有明确型号
      · `VRP (R) software, Version 5.110 (S5700 V200R001C00)` → 型号在括号里
      · `VRP WVSP Software Version VRPV500R003C07`            → 安全设备，无型号行，
                                                                   靠配置里的 firewall zone 判定
    """
    from core.topology_flood import parse_model

    got = parse_model(ver)
    if got:
        return got
    m = re.search(r"\(([A-Za-z]\w{1,10})\s+V\d{3}R\d{3}", ver)
    if m:
        return m.group(1)
    if re.search(r"^firewall\s+zone|^security-policy|^security-zone", cfg, re.M):
        return "USG/SRG(防火墙)"
    m = re.search(r"\b(S\d{4}|AR\d{3,4}|USG\d{4}V?|SRG\d*)\b", ver)
    return m.group(1) if m else ""


def collect(host: str, port: int, timeout: float = 20.0) -> dict:
    t0 = time.time()
    try:
        s = TelnetSession(host, port, connect_timeout=8.0, timeout=timeout)
        try:
            s.drain()
            s.prepare()
            # 提示符里有 sysname（eNSP 设备默认不写 sysname 行，只能从提示符取）
            s.write_line("")
            time.sleep(0.4)
            prompt_raw = s.drain(quiet=0.5, limit=3.0)
            ver = s.exec_command("display version")
            cfg = s.exec_command("display current-configuration")
        finally:
            s.close()
    except Exception as e:  # 单台失败不影响整轮
        return {"port": port, "sysname": "", "model": "", "role_guess": "采集失败",
                "features": {}, "config_lines": 0,
                "error": f"{type(e).__name__}: {e}", "seconds": round(time.time() - t0, 1)}

    m = re.search(r"[<\[\(]([^<>\[\]\(\)\r\n]{1,24})[>\])]", prompt_raw)
    sysname = m.group(1).strip() if m else ""
    model = detect_model(ver, cfg)
    dev = extract(cfg, model, port, sysname)
    if not dev["sysname"]:
        dev["sysname"] = (dev["features"].get("sysname") or [""])[0]
    dev["seconds"] = round(time.time() - t0, 1)
    dev["_cfg"] = cfg
    return dev


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="拉取 eNSP 全部设备的当前配置并生成摘要")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--ports", default="2000-2020", help="端口区间，如 2000-2020 或 2000,2003")
    ap.add_argument("--out", default="", help="输出目录（默认 data/lab_reports/current_<ts>）")
    args = ap.parse_args(argv[1:])

    ports: list[int] = []
    for part in args.ports.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            ports.extend(range(int(a), int(b) + 1))
        elif part:
            ports.append(int(part))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else BASE_DIR / "data" / "lab_reports" / f"current_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"目标 {args.host}，端口 {len(ports)} 个 → {out_dir}")
    results: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for dev in ex.map(lambda p: collect(args.host, p), ports):
            results.append(dev)
            tag = "OK " if not dev.get("error") else "ERR"
            print(f"  [{tag}] {dev['port']} {dev['sysname'] or '-':<12} {dev['role_guess']:<16}"
                  f" {dev.get('config_lines', 0):>5} 行 {dev.get('seconds')}s"
                  + (f"  {dev.get('error','')[:50]}" if dev.get("error") else ""))

    results.sort(key=lambda d: d["port"])
    digest_txt = "\n".join(summarize(d) for d in results)
    (out_dir / "digest.txt").write_text(digest_txt, encoding="utf-8")

    for d in results:
        cfg = d.pop("_cfg", "")
        name = re.sub(r"[^\w\-]", "_", d["sysname"] or "noname")
        (out_dir / f"{d['port']}_{name}.cfg").write_text(cfg, encoding="utf-8")
        d["cfg_file"] = f"{d['port']}_{name}.cfg"
    (out_dir / "digest.json").write_text(
        json.dumps({"host": args.host, "time": ts, "devices": results},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for d in results if not d.get("error"))
    print(f"\n完成：{ok}/{len(results)} 台采集成功；摘要 {out_dir / 'digest.txt'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
