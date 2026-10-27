"""探测 VRP 命令行的上下文帮助（`?`），用于确认本机 VRP 版本支持的确切语法。

为什么需要：不同 VRP 版本的命令族差异很大（如 IPv6 VRRP 在部分版本是 `vrrp6`
而非 `vrrp ... virtual-ipv6`，且虚拟地址的 link-local / 全局顺序有强约束）。
靠记忆猜命令会反复踩 "Wrong parameter"，直接问设备最快。

用法：
    python tools/lab_help.py --port 2001 --enter "system-view,interface Vlanif10" --cmd "vrrp6 vrid 10 virtual-ip"

`?` 必须**不带换行**发送，且要连发两次（第一次 VRP 回显命令本身并列出候选）。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.device_conn import TelnetSession  # noqa: E402

HOST = os.environ.get("LAB_HOST", "192.168.183.137")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="探测 VRP `?` 帮助")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=2001)
    ap.add_argument("--enter", default="", help="进入视图的命令，逗号分隔")
    ap.add_argument("--cmd", required=True, help="要补全的命令前缀")
    ap.add_argument("--out", default="")
    ap.add_argument("--timeout", type=float, default=12.0)
    args = ap.parse_args(argv[1:])

    sess = TelnetSession(args.host, args.port, connect_timeout=8.0, timeout=args.timeout)
    chunks: list[str] = []
    try:
        sess.drain()
        sess.prepare()
        sess.exec_command("return", timeout=args.timeout)
        for step in [s.strip() for s in args.enter.split(",") if s.strip()]:
            chunks.append(f"\n---- [enter] {step}\n" + (sess.exec_command(step, timeout=args.timeout) or ""))
        # `?` 不能带回车：先写命令文本，再写 "?"，然后读
        sess.write_line(args.cmd + " ?")
        time.sleep(1.2)
        chunks.append(f"\n---- [?] {args.cmd} ?\n" + (sess.drain(quiet=1.0, limit=8.0) or ""))
        # 结束：Ctrl+C 清掉残行
        try:
            sess.sock.sendall(b"\x03")
            time.sleep(0.3)
            sess.drain(quiet=0.4, limit=2.0)
        except Exception:
            pass
    finally:
        sess.close()

    text = "\n".join(chunks)
    out = Path(args.out) if args.out else BASE_DIR / "logs" / f"help_{args.port}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"写入 {out} ({len(text)} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
