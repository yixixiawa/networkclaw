"""对 WAN 岛剩余「静默端点」跑全配对矩阵，找出直连链路。

原理：两个直连的路由器端口配同一 /30 后必然互通；不通即非直连。
每个被测端口先 undo 旧探测地址再配新地址（需 NETWORKCLAW_LAB_MODE=1）。

用法：
    NETWORKCLAW_LAB_MODE=1 python tools/probe_pair_matrix.py --out logs/pair_matrix.txt
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from itertools import combinations
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
APPLY = [str(BASE / ".venv" / "Scripts" / "python.exe"), str(BASE / "tools" / "lab_apply.py")]

# 端点清单：全部是「LLDP 无邻居、MAC 无学习、且未被之前配对测试命中」的端口
ENDPOINTS = [
    (2000, "GigabitEthernet0/0/5"),   # FW0 剩余口（GE0/0/1 已测=2018 方向）
    (2012, "Ethernet0/0/0"),          # D12
    (2012, "GigabitEthernet0/0/0"),
    (2012, "GigabitEthernet0/0/1"),
    (2020, "Ethernet0/0/0"),          # D20
    (2020, "Ethernet0/0/1"),
    (2009, "GigabitEthernet0/0/0"),   # R9 空闲口
]

FIREWALLS = {2000, 2010}


def apply_cmds(port: int, cmds: list[str]) -> tuple[bool, str]:
    import os
    import time
    env = {**os.environ, "NETWORKCLAW_LAB_MODE": "1"}
    p = subprocess.run(APPLY + ["--ports", str(port), "--cmds", ";".join(cmds),
                                "--apply", "--timeout", "20", "--verbose"],
                       capture_output=True, text=True, env=env, timeout=240, cwd=str(BASE))
    time.sleep(1.5)  # eNSP 控制台是单会话，连续快速重连会触发「占用」预检失败
    return p.returncode == 0, p.stdout


def set_ip(port: int, iface: str, ip: str) -> bool:
    cmds = ["system-view", f"interface {iface}", "undo ip address",
            f"ip address {ip} 255.255.255.252"]
    if port in FIREWALLS:
        cmds.append("service-manage ping permit")
    cmds += ["quit", "quit"]
    ok, out = apply_cmds(port, cmds)
    return ok and "Error" not in out


def ping_from(port: int, target: str) -> str:
    ok, out = apply_cmds(port, [f"ping {target}"])
    if not ok:
        return "(session error)"
    m = re.search(r"([0-9.]+)% packet loss", out)
    if m:
        return m.group(1) + "% loss"
    # 回显异常时带一段原文尾部便于排查（不判断 = 探测无效）
    tail = " | ".join(ln.strip() for ln in out.strip().splitlines()[-2:])
    return f"(raw) {tail[:120]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="logs/pair_matrix.txt")
    args = ap.parse_args()

    lines: list[str] = []
    n = 0
    for (p1, i1), (p2, i2) in combinations(ENDPOINTS, 2):
        if p1 == p2:
            continue  # 同一设备的两个端口不可能互联
        n += 1
        # /30 子网：10.199.<n>.0/30 → .1 / .2
        subnet = f"10.199.{n}"
        ip1, ip2 = f"{subnet}.1", f"{subnet}.2"
        ok1 = set_ip(p1, i1, ip1)
        ok2 = set_ip(p2, i2, ip2)
        if not (ok1 and ok2):
            res = "(config failed)"
        else:
            res = ping_from(p1, ip2)
        tag = f"MATCH! {p1}:{i1} <-> {p2}:{i2}" if res == "0% loss" else f"no      {p1}:{i1} <-> {p2}:{i2}"
        lines.append(f"{tag}   [{res}]  ips={ip1}/{ip2}")
        print(lines[-1], flush=True)

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"\n共 {n} 对，结果已写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
