"""按设备批量下发配置命令（**必经 command_guard + 审计日志**）。

为什么不让模型逐条调 exec_telnet_command：
    一个「双核心 + 双出口 + 防火墙 + 分支」的配置动辄上百条命令，逐条走模型一轮
    30s 起，且 9B 模型在长会话里极易漏条/串台。命令内容由设计（人或模型）产出，
    **执行必须确定性**——这个脚本就是那个执行器。

安全边界（不可妥协，与 MCP 工具同一套判定）：
    · 每条命令都过 core.command_guard.check(confirmed=True)，block 级直接拒绝；
    · 每条命令都写 logs/command_audit.log（密码不落盘）；
    · 默认 --dry-run，只有显式 --apply 才真的下发；
    · 单个设备失败不影响其它设备，失败原因逐台打印。

两种用法：
    # 1) 所有端口下发同一组命令（如开 LLDP）
    python tools/lab_apply.py --ports 2000-2020 --cmds "system-view;lldp enable;quit" --apply

    # 2) 按设备下发不同配置（plan.json：{"2001": ["system-view", "sysname HQ-CORE1", ...]}）
    python tools/lab_apply.py --plan plans/hq_core.json --apply

plan.json 里可以写 "host" 覆盖默认 LAB_HOST。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.command_guard import audit, check  # noqa: E402
from core.device_conn import TelnetSession  # noqa: E402

HOST = os.environ.get("LAB_HOST", "192.168.183.137")


def parse_ports(spec: str) -> list[int]:
    ports: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            ports.extend(range(int(a), int(b) + 1))
        elif part:
            ports.append(int(part))
    return ports


def _prompt_alive(sess, timeout: float) -> bool:
    """探活：敲回车能否读到提示符；不行就发 Ctrl+Z / Ctrl+C 复位后重试一次。"""
    import re as _re
    for attempt in range(2):
        try:
            sess.write_line("")
            text = sess.drain(quiet=0.6, limit=3.0)
        except Exception:
            text = ""
        if _re.search(r"[<\[][^<>\[\]\r\n]{1,30}[>\]]", text or ""):
            return True
        for seq in ("\x03", "\x1a"):
            try:
                sess.sock.sendall(seq.encode())
                time.sleep(0.3)
            except Exception:
                break
        try:
            sess.write_line("")
        except Exception:
            pass
    return False


def _normalize_view(sess, timeout: float) -> str:
    """把设备拉回**用户视图**，返回最终提示符。

    为什么要这一步：eNSP 控制台是单会话长连，上一次下发如果中途结束（超时/异常），
    设备会残留在 system-view 甚至 interface 视图。下一次再发 `system-view` 就会
    报 `Error: Unrecognized command found at '^' position.`，后续命令全部错位
    （2026-10-23 实测：vrrp 命令被当成用户视图命令执行）。
    `return` 在 VRP 里从任意视图直接回用户视图，且护栏判 allow，可以无脑发。
    """
    import re as _re
    text = ""
    for _ in range(3):
        try:
            text = sess.exec_command("return", timeout=timeout) or ""
        except Exception:
            break
        if _re.search(r"^<[^<>]{1,40}>", text.strip().splitlines()[-1] if text.strip() else ""):
            return text
        if _re.search(r"<[^<>]{1,40}>", text):
            return text
    return text


def apply_to(host: str, port: int, commands: list[str], dry_run: bool,
             timeout: float = 25.0) -> dict:
    """对一台设备按顺序下发命令；返回执行摘要"""
    t0 = time.time()
    result = {"port": port, "ok": True, "applied": 0, "blocked": [], "errors": [], "log": []}

    # 先做静态判定：任何一条是 block 级，整台设备都不下发（避免半套配置）
    verdicts = []
    for cmd in commands:
        allowed, message, decision = check(cmd, confirmed=True)
        verdicts.append((cmd, allowed, message, decision))
        if not allowed:
            result["blocked"].append({"cmd": cmd, "reason": message})
    if result["blocked"]:
        result["ok"] = False
        return result

    if dry_run:
        result["log"] = [f"[dry] {c}" for c in commands]
        return result

    sess = None
    try:
        sess = TelnetSession(host, port, connect_timeout=8.0, timeout=timeout)
        sess.drain()
        sess.prepare()
        # 预检：eNSP 控制台是单会话，上一次被强杀的连接会短期「占着」控制台，
        # 表现为连上但一个字节都不回（实测 60 条命令全超时，白等 6 分钟）。
        # 这里先敲回车看有没有提示符，没有就 Ctrl+Z / Ctrl+C 复位，再不行就跳过这台。
        if not _prompt_alive(sess, timeout):
            result["ok"] = False
            result["errors"].append({"cmd": "(preflight)",
                                     "out": "控制台无响应（可能被上一次会话占用），已跳过"})
            return result
        _normalize_view(sess, timeout)
        for cmd, _allowed, _msg, decision in verdicts:
            audit(cmd, decision, transport="telnet", target=f"{host}:{port}",
                  confirmed=True, executed=True)
            out = sess.exec_command(cmd, timeout=timeout)
            # VRP 有些命令会追问 [Y/N]（如改 STP 模式、覆盖已有配置）：
            # 不回答会让后续所有命令都等不到提示符（2026-10-23 实测：整台设备 60 条全超时）。
            if out and re.search(r"\[Y/N\]|\[y/n\]|Continue\?", out):
                out += "\n" + (sess.exec_command("y", timeout=timeout) or "")
            result["applied"] += 1
            result["log"].append(f"> {cmd} :: {(out or '').strip().splitlines()[-1][:90] if out else ''}")
            if out and any(k in out for k in ("Error", "Wrong parameter", "Unrecognized", "Incomplete")):
                result["errors"].append({"cmd": cmd, "out": out.strip()[:200]})
    except Exception as e:
        result["ok"] = False
        result["errors"].append({"cmd": "(session)", "out": f"{type(e).__name__}: {e}"})
    finally:
        if sess is not None:
            sess.close()

    result["seconds"] = round(time.time() - t0, 1)
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="批量下发配置（过命令护栏 + 写审计）")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--ports", default="2000-2020")
    ap.add_argument("--cmds", default="", help="用 ; 分隔的命令序列（对所有端口）")
    ap.add_argument("--plan", default="", help="按设备区分的 JSON：{port: [cmd,...]} 或 {port: {cmds:[...]}}")
    ap.add_argument("--apply", action="store_true", help="真的下发（默认 dry-run）")
    ap.add_argument("--timeout", type=float, default=15.0, help="单条命令等待回显秒数，默认 15")
    ap.add_argument("--verbose", action="store_true", help="逐条打印回显")
    args = ap.parse_args(argv[1:])

    plan: dict[int, list[str]] = {}
    if args.plan:
        raw = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        host = str(raw.pop("host", args.host)) if isinstance(raw, dict) else args.host
        for k, v in raw.items():
            if str(k).startswith("_"):
                continue
            cmds = v.get("cmds") if isinstance(v, dict) else v
            plan[int(k)] = [str(c) for c in cmds]
    else:
        host = args.host
        cmds = [c.strip() for c in args.cmds.split(";") if c.strip()]
        if not cmds:
            print("要么给 --cmds，要么给 --plan")
            return 2
        plan = {p: cmds for p in parse_ports(args.ports)}

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] {host} · {len(plan)} 台设备")
    failures = 0
    for port in sorted(plan):
        r = apply_to(host, port, plan[port], dry_run=not args.apply, timeout=args.timeout)
        status = "OK " if r["ok"] and not r["errors"] else "ERR"
        if not r["ok"]:
            failures += 1
        print(f"  [{status}] {port}: 下发 {r['applied']} 条"
              + (f" 拦截 {len(r['blocked'])} 条：{r['blocked'][0]['reason'][:60]}" if r["blocked"] else "")
              + (f" 报错 {len(r['errors'])} 条：{r['errors'][0]['cmd']} → {r['errors'][0]['out'][:60]}" if r["errors"] else ""))
        if args.verbose or not args.apply:
            for line in r["log"][: None if args.verbose else 6]:
                print(f"        {line}")
    print(f"\n设备级失败 {failures} 台")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
