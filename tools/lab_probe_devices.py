"""通过 Telnet 探测当前实验设备的可用性（不经过 eNSP GUI）。

设备 console 端口映射来自 `knowledge/experiments/NN-*.md` 的设备清单表
（data/ensp_labs/src 里解析出来的）。

用法:
    python tools/lab_probe_devices.py 01
    python tools/lab_probe_devices.py 01 --cmd "display version"
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.device_conn import TelnetSession, probe_tcp  # noqa: E402

HOST = "192.168.10.130"
DOC_DIR = BASE_DIR / "knowledge" / "experiments"


def load_devices(num: str) -> list[tuple[str, int, str]]:
    """从实验文档的设备表里读出 (设备名, console 端口, 型号)。"""
    hits = sorted(DOC_DIR.glob(f"{num}-*.md"))
    if not hits:
        raise SystemExit(f"没有找到实验 {num} 的文档（{DOC_DIR}）")
    text = hits[0].read_text(encoding="utf-8")
    devs: list[tuple[str, int, str]] = []
    for line in text.splitlines():
        m = re.match(r"^\|\s*([A-Za-z0-9_-]+)\s*\|\s*([^|]+?)\s*\|\s*(\d+|-)\s*\|", line)
        if m:
            name, model, port = m.group(1), m.group(2).strip(), m.group(3)
            if port.isdigit():
                devs.append((name, int(port), model))
    return devs


def console_dead(last_err: str) -> bool:
    """console 完全没有可读字符（典型：AR 未真正启动，回显只有 '##\\x00'）。

    这种情况下重试再多次也是同一个结果——一个实验白烧 25 分钟，
    39 个含路由器的实验就是 16 小时。识别出来就立刻放弃，把时间留给别的实验。
    """
    m = re.search(r"设备回显片段：(.*)$", last_err)
    if not m:
        return False
    return not re.search(r"[A-Za-z0-9]", m.group(1))


def is_router(model: str) -> bool:
    """路由器（AR2220 等）比交换机难伺候：VRP 启动要几分钟。"""
    return bool(re.search(r"(?i)\bAR\d|ROUTER|\bNE\d", model or ""))


def probe_all(num: str, host: str = HOST, cmd: str = "display version",
              retries: int = 3, retry_gap: float = 8.0) -> list[dict]:
    """探测实验里所有可管理设备，返回 [{name, port, model, ok, detail}]。

    刚启动的设备 console 还没就绪（回显像 '##\\x00'），所以失败要重试。

    路由器单独放宽（2026-10-01 实验 03 实测）：Telnet 端口一开放，eNSP 就认为
    「设备已启动」，但 AR2220 的 VRP 还在加载，此时连上去只有 '##\\x00'。
    交换机 15s 登录超时够用，路由器要 60s + 6 次重试（约 3 分钟）才稳。

    放宽的前提是路由器**有可能起来**。嵌套虚拟化不可用时（issues P23：宿主机开了
    VBS/Hyper-V，VMware 不再向来宾透传 AMD-V），AR 是 VirtualBox 虚拟机、
    根本不可能启动，放宽超时只是把 3 分钟×3 台白烧掉——这种时候按交换机处理，
    让 console_dead() 立刻识别并放弃。
    """
    import time as _time

    from tools.nested_virt import router_can_boot

    devs = load_devices(num)
    print(f"实验 {num}：{len(devs)} 个可管理设备 -> {[d[0] for d in devs]}")
    out_rows: list[dict] = []
    for name, port, model in devs:
        row = {"name": name, "port": port, "model": model, "ok": False, "detail": ""}
        p = probe_tcp(host, port, timeout=3)
        if not p.get("ok"):
            row["detail"] = "端口未开放"
            print(f"[{name}] {host}:{port} 端口未开放")
            out_rows.append(row)
            continue
        router = is_router(model) and router_can_boot()
        tries = 6 if router else retries
        gap = 25.0 if router else retry_gap
        login_to = 60.0 if router else 15.0
        if router:
            print(f"[{name}] {model} 是路由器，放宽登录超时到 {login_to:g}s / 重试 {tries} 次")
        elif is_router(model):
            print(f"[{name}] {model} 是路由器，但本机不支持嵌套虚拟化（P23），"
                  f"按交换机超时处理（{login_to:g}s / {tries} 次）")
        last_err = ""
        for attempt in range(1, tries + 1):
            s = TelnetSession(host, port, timeout=25)
            try:
                s.login(timeout=login_to)
                s.prepare()
                res = s.exec_command(cmd, timeout=30)
                first = " / ".join(res.strip().splitlines()[:6])
                row["ok"] = True
                row["detail"] = first[:200]
                print(f"[{name}] {host}:{port} OK  {first[:200]}")
                break
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__} {e}"
                if console_dead(last_err):
                    # 回显是纯二进制噪声：不是"还没启动完"，是压根没起来，重试无意义
                    last_err = ("console 无可读输出（设备可能根本没启动，"
                                "eNSP 只是先把端口开出来了）")
                    print(f"[{name}] {last_err}，放弃重试")
                    break
                if attempt < tries:
                    print(f"[{name}] 第 {attempt} 次失败，{gap:g}s 后重试：{last_err[:90]}")
                    _time.sleep(gap)
            finally:
                try:
                    s.close()
                except Exception:  # noqa: BLE001
                    pass
        if not row["ok"]:
            row["detail"] = last_err
            print(f"[{name}] {host}:{port} 失败：{last_err}")
        out_rows.append(row)
    return out_rows


def main(argv: list[str]) -> int:
    num = argv[1] if len(argv) > 1 else "01"
    cmd = "display version"
    if "--cmd" in argv:
        cmd = argv[argv.index("--cmd") + 1]
    probe_all(num, cmd=cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
