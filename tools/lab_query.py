"""对指定设备执行只读查询命令，把**完整回显**落到文件（终端 stdout 常被吞）。

为什么单独一个脚本：
    tools/lab_apply.py 是「按计划下发配置」的执行器，--verbose 只打印每条命令的
    最后一行，排查 OSPFv3 邻居/路由表这类多行表格时不够用。诊断需要完整原文。

只用 display 类命令（command_guard 判 allow），不会改设备。

用法：
    python tools/lab_query.py --ports 2001,2002 --cmds "display ospfv3 peer;display ipv6 interface brief"
    python tools/lab_query.py --ports 2001 --cmds "display current-configuration | include ospfv3" --out logs/q.txt
"""
from __future__ import annotations

import argparse
import json
import os
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


def _reset_console(sess, timeout: float) -> str:
    """清掉控制台上残留的半条命令，返回当前提示符。

    eNSP 控制台是**单会话长连**：上一个脚本如果中途被 Ctrl+C/超时掐断，残行会留在
    设备行缓冲里，下一个人连上来发的第一条命令会和残行拼在一起，导致回显全空
    （2026-10-23 实测：一次被 SIGTERM 的批量查询之后，2003/2004/2005 的
    `display interface brief` 全返回空串，而同一命令在 2001/2002 正常）。
    Ctrl+C 在 VRP 里丢弃当前行并重发提示符，是复位这一步的标准手段。
    """
    try:
        sess.sock.sendall(b"\x03")
    except Exception:
        pass
    time.sleep(0.3)
    try:
        sess.write_line("")
    except Exception:
        pass
    return sess.drain(quiet=0.6, limit=3.0) or ""


def query(host: str, port: int, cmds: list[str], timeout: float = 20.0) -> dict:
    out = {"port": port, "ok": True, "results": []}
    sess = None
    try:
        sess = TelnetSession(host, port, connect_timeout=8.0, timeout=timeout)
        sess.drain()
        sess.prepare()
        prompt = _reset_console(sess, timeout)
        # 只在**非用户视图**时才发 return。
        # AR201（eNSP V5.110）在用户视图下执行 `return` 会吞掉后续第一条命令的全部
        # 回显；S5700/AR2220 无此问题。按提示符判断后再决定，最稳。
        last = prompt.strip().splitlines()[-1] if prompt.strip() else ""
        if "[" in last:
            sess.exec_command("return", timeout=timeout)
        for cmd in cmds:
            allowed, message, decision = check(cmd, confirmed=True)
            if not allowed:
                out["results"].append({"cmd": cmd, "text": f"[拦截] {message}"})
                continue
            audit(cmd, decision, transport="telnet", target=f"{host}:{port}",
                  confirmed=True, executed=True)
            text = sess.exec_command(cmd, timeout=timeout) or ""
            if "]]>" in text or text.rstrip().endswith("---- More ----"):
                text += sess.drain(quiet=0.8, limit=6.0) or ""
            out["results"].append({"cmd": cmd, "text": text})
    except Exception as e:
        out["ok"] = False
        out["results"].append({"cmd": "(session)", "text": f"{type(e).__name__}: {e}"})
    finally:
        if sess is not None:
            sess.close()
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="只读查询（display），完整回显落文件")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--ports", default="2001")
    ap.add_argument("--cmds", required=True, help="用 ; 分隔")
    ap.add_argument("--out", default="", help="输出文件，默认 logs/lab_query_<ts>.txt")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args(argv[1:])

    cmds = [c.strip() for c in args.cmds.split(";") if c.strip()]
    ports = parse_ports(args.ports)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else BASE_DIR / "logs" / f"lab_query_{ts}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    chunks = [f"# host={args.host} ports={ports} ts={ts}"]
    for port in ports:
        r = query(args.host, port, cmds, timeout=args.timeout)
        chunks.append(f"\n{'='*78}\n## port {port}  ok={r['ok']}\n{'='*78}")
        for item in r["results"]:
            chunks.append(f"\n---- $ {item['cmd']}\n{item['text'].strip()}")
    text = "\n".join(chunks)
    out_path.write_text(text, encoding="utf-8")
    print(f"写入 {out_path}  ({len(text)} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
