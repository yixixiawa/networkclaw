"""以**完全脱离**的方式启动一个后台进程（日志落文件）。

为什么需要它：
    跑一个 eNSP 实验要十几分钟到几十分钟（本地 9B 模型生成约 2.3 t/s，
    一轮对话就得一分钟）。而调度器给后台任务的超时是 2 分钟，进程会被回收，
    表现为「日志停在第 1 轮就没了」。DETACHED_PROCESS 启动的进程不属于
    任何作业对象，父进程退出后继续跑，日志实时落盘。

    本机 PowerShell 的 Start-Process 还有个坑：会话里同时存在 `Path` 与 `PATH`
    两个键（大小写不同），Start-Process 构造环境变量字典时直接抛
    「已添加项。字典中的关键字:"Path"」——所以走 Python 的 subprocess 更稳。

用法：
    python tools/spawn.py <日志文件> <命令> [参数...]
    python tools/spawn.py logs/run01.txt .\\.venv\\Scripts\\python.exe tools\\lab_run_agent.py 01
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def spawn(log_file: str, cmd: list[str], extra_env: dict | None = None) -> int:
    out = Path(log_file)
    if not out.is_absolute():
        out = BASE_DIR / out
    out.parent.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("FASTMCP_LOG_LEVEL", "ERROR")   # FastMCP 的 banner 很吵
    env.update(extra_env or {})

    flags = 0
    if os.name == "nt":
        # DETACHED_PROCESS 只脱离控制台，不脱离**作业对象**：调度器如果把整棵进程树
        # 放进 Job 并在任务结束时 kill job，批量任务照样被回收（2026-10-01 实测：
        # 三次批量都停在起设备的静默等待处，无异常、无 traceback）。
        # CREATE_BREAKAWAY_FROM_JOB 让子进程不属于任何 Job，才是真正的"跑掉"。
        flags = (subprocess.DETACHED_PROCESS
                 | subprocess.CREATE_NEW_PROCESS_GROUP
                 | 0x01000000)  # CREATE_BREAKAWAY_FROM_JOB

    f = out.open("wb")
    proc = subprocess.Popen(
        cmd, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        cwd=str(BASE_DIR), env=env, creationflags=flags, close_fds=True,
    )
    f.close()  # 父进程不持有句柄，子进程自己写
    print(f"pid={proc.pid} log={out}")
    return proc.pid


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    spawn(argv[1], argv[2:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
