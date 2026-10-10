"""批量跑完所有 eNSP 实验（无人值守，可断点续跑）。

每轮对每个实验做四件事：起设备 → 探测设备 → 本地模型配置 → 验收比对，
结果追加到 data/lab_reports/index.csv（断点续跑的依据），
模型输出与下发命令落到 data/run_logs/<日期>/ 下（微调数据集的原料）。

用法：
    python tools/lab_batch.py                      # 跑全部（跳过已完成）
    python tools/lab_batch.py --from 02 --to 10    # 只跑 02~10
    python tools/lab_batch.py --only 03,07         # 只跑指定编号
    python tools/lab_batch.py --redo 03            # 强制重跑（忽略已完成记录）
    python tools/lab_batch.py --dry-run            # 只列清单不执行

注意：起设备要靠 VM 里的 eNSP GUI，跑之前确认 vmrun 可用、来宾已开机。
"""
from __future__ import annotations

import argparse
import asyncio
import builtins
import csv
import functools
import os
import re
import sys
import time
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# 批量任务一跑就是几小时，日志必须实时落盘（重定向到文件时 stdout 是块缓冲）
print = functools.partial(builtins.print, flush=True)  # noqa: A001

from tools.lab_run_agent import REPORT_DIR, HOST, run_lab  # noqa: E402

INDEX_CSV = REPORT_DIR / "index.csv"
FIELDS = ["num", "name", "devices", "reachable", "tool_calls", "hit", "total",
          "pct", "hit_before", "net", "elapsed", "status", "report", "error"]


def ensure_server(ctx: int = 16384, restart: bool = False) -> str:
    """确保本地 llama-server 在跑。

    跑久了 KV cache 会被历史请求占满，推理速度肉眼可见地变慢
    （实测从 ~30 t/s 掉到 ~2 t/s）。所以批量任务默认**每个实验前重启一次**，
    把上下文和缓存整个清掉——这是最有效的提速手段，代价只是多花 1~2 分钟加载模型。

    上下文默认 16K：够装工具 schema + 十几轮回显，又不至于让 KV cache 太大拖慢推理。
    """
    from core import llama_start as ls

    if restart:
        ls.kill_all_llama_servers()
        for _ in range(60):  # 等端口真正释放，最多 30 秒
            if not ls.is_server_running():
                break
            time.sleep(0.5)
    if ls.is_server_running():
        return f"复用已运行的 llama-server（{ls.BASE_URL}）"
    os.environ["NETWORKCLAW_CTX"] = str(ctx)
    proc = ls.start_llama_server()
    return (f"已重启 llama-server（ctx={ctx}）" if proc
            else "llama-server 启动失败或已被其他实例占用")


def read_index() -> dict[str, dict]:
    if not INDEX_CSV.exists():
        return {}
    with INDEX_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        return {r["num"]: r for r in csv.DictReader(f)}


def append_index(row: dict) -> None:
    """写索引。同一实验重跑时**覆盖**旧行，不追加。

    纯追加会让 `--redo` 过的实验在 CSV 里留多行（实测 02 留了 3 行），
    统计"已完成/平均命中率"时全部失真。
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    old = [r for r in read_index().values() if r.get("num") != row.get("num")]
    old.append({k: row.get(k, "") for k in FIELDS})
    old.sort(key=lambda r: str(r.get("num", "")))
    with INDEX_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in old:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def all_nums() -> list[tuple[str, str]]:
    """返回 [(编号, 实验名)]。

    编号与实验名一律以 `knowledge/experiments/NN-<实验名>.md` 为准——
    那里是 ensp_lab_index.py 生成的唯一权威编号；data/ensp_labs/src 的目录名
    不含数字前缀（例如「ACCESS、TRUNK、HYBRID配置练习」），不能拿来当编号。
    """
    from tools.lab_run_agent import DOC_DIR

    out = []
    for fp in sorted(DOC_DIR.glob("*.md")):
        m = re.match(r"^(\d+)-(.+)\.md$", fp.name)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def select(args) -> list[tuple[str, str]]:
    items = all_nums()
    if args.only:
        want = {x.strip().zfill(2) for x in args.only.split(",") if x.strip()}
        return [x for x in items if x[0] in want]
    # 00 是索引总览文档，不是实验，默认从 01 开始
    lo = args.frm.zfill(2) if args.frm else "01"
    hi = args.to.zfill(2) if args.to else "99"
    return [x for x in items if lo <= x[0] <= hi]


async def main_async(args) -> int:
    items = select(args)
    done = read_index()
    redo = {x.strip().zfill(2) for x in (args.redo or "").split(",") if x.strip()}

    print(f"实验总数 {len(items)}，已有记录 {len(done)}")
    if args.dry_run:
        for num, name in items:
            print(f"  {num}  {name}  {'[已完成]' if num in done else ''}")
        return 0

    # 开头不重启：此刻要么是刚拉起的干净实例，要么是用户在用的实例（不该被我们杀掉）
    print(ensure_server(args.ctx, restart=False))

    ok = fail = skip = 0
    ran = 0  # 已实际执行的实验数（用于按间隔重启模型）
    for i, (num, name) in enumerate(items, 1):
        if num in done and num not in redo and not args.force:
            print(f"\n[{i}/{len(items)}] {num} {name} —— 已有记录，跳过")
            skip += 1
            continue
        # 长跑会拖慢推理：每 N 个实验重启一次模型，把 KV cache 清空
        if ran > 0 and args.restart_every > 0 and ran % args.restart_every == 0:
            print(f"\n[维护] 已跑 {ran} 个实验，重启模型清理上下文 …")
            print(ensure_server(args.ctx, restart=True))
        ran += 1
        print(f"\n{'=' * 64}\n[{i}/{len(items)}] 实验 {num}：{name}\n{'=' * 64}")
        row = {"num": num, "name": name, "status": "error"}
        try:
            res = await run_lab(num, host=args.host, rounds=args.rounds,
                                do_up=not args.no_up, wait=args.wait)
            if not res.get("ok"):
                row.update(status="abort", error=res.get("reason", ""))
                fail += 1
            else:
                v = res.get("verify") or []
                hit = sum(x.get("hit", 0) for x in v)
                total = sum(x.get("total", 0) for x in v)
                hit_before = sum(x.get("hit_before", 0) for x in v)
                row.update(
                    hit_before=hit_before, net=hit - hit_before,
                    devices=len(res.get("probe") or []),
                    reachable=sum(1 for r in (res.get("probe") or []) if r["reachable"]),
                    tool_calls=res.get("model", {}).get("tool_calls", 0),
                    hit=hit, total=total,
                    pct=round(hit * 100 / total, 1) if total else "",
                    elapsed=res.get("model", {}).get("elapsed", 0),
                    status="ok", report=res.get("report", ""),
                )
                ok += 1
        except Exception as e:  # noqa: BLE001
            row.update(status="error", error=f"{type(e).__name__}: {e}"[:300])
            print(traceback.format_exc()[-1500:])
            fail += 1
        append_index(row)
        print(f">>> {num} 结果：{row['status']} {row.get('pct', '')}")

    print(f"\n{'=' * 64}\n完成：成功 {ok} ｜ 中止 {fail} ｜ 跳过 {skip}")
    print(f"索引：{INDEX_CSV}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="批量跑 eNSP 实验")
    ap.add_argument("--from", dest="frm", default="")
    ap.add_argument("--to", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--redo", default="")
    ap.add_argument("--force", action="store_true", help="忽略已完成记录，全部重跑")
    ap.add_argument("--no-up", action="store_true", help="跳过起设备（设备已起）")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--rounds", type=int, default=40)
    ap.add_argument("--wait", type=int, default=900,
                    help="等 Telnet 端口的秒数（路由器比交换机慢，300s 常不够）")
    ap.add_argument("--ctx", type=int, default=16384, help="llama-server 上下文大小")
    ap.add_argument("--restart-every", type=int, default=1,
                    help="每跑几个实验重启一次模型清理 KV cache（0=不重启）")
    ap.add_argument("--dry-run", action="store_true")
    return asyncio.run(main_async(ap.parse_args(argv[1:])))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
