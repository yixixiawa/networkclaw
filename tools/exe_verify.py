"""打包产物（dist/NetworkClaw/NetworkClaw.exe）端到端验证。

三件事，全部把结论写进 logs/exe_verify_result.txt：

    1. --serve-mcp 派发：用 exe 自身当 MCP 服务端拉起（knowledge + device-serial），
       列工具并真实调用一次 —— 覆盖「runpy 动态模块」「标准流修复」「chromadb 打包」
    2. GUI 身份：离屏模式拉起 exe，12 秒后确认进程仍活着、未写 launcher_error.log
    3. 种子释放：确认 ensure_user_data 已把 knowledge/ 等释放到 exe 旁边

用法：
    .venv/Scripts/python.exe tools/exe_verify.py [exe路径]
    # 默认 exe 路径：dist/NetworkClaw/NetworkClaw.exe
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULT = ROOT / "logs" / "exe_verify_result.txt"
lines: list[str] = []


def log(text: str = "") -> None:
    lines.append(text)
    try:
        RESULT.parent.mkdir(parents=True, exist_ok=True)
        RESULT.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass


def check(label: str, ok: bool, detail: str = "") -> None:
    log(f"  [{'✓' if ok else '✗'}] {label}" + (f" —— {detail}" if detail else ""))


async def test_serve_mcp(exe: Path, name: str, call: dict | None) -> None:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    t0 = time.time()
    env = os.environ.copy()
    # 与 MCP 客户端运行时一致的子进程环境（清掉可能劫持回环的代理）
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(k, None)
    env.setdefault("NO_PROXY", "127.0.0.1,localhost")
    try:
        transport = StdioTransport(str(exe), [f"--serve-mcp", name], env=env)
        async with Client(transport) as client:
            tools = await client.list_tools()
            dt = time.time() - t0
            check(f"--serve-mcp {name} 连接", True,
                  f"{len(tools)} 个工具，用时 {dt:.1f}s：{', '.join(t.name for t in tools)}")
            if call:
                tool, args = call
                t1 = time.time()
                res = await client.call_tool(tool, args)
                text = "".join(getattr(b, "text", "") for b in res.content)[:400]
                check(f"--serve-mcp {name} 调用 {tool}", True,
                      f"用时 {time.time() - t1:.2f}s，响应开头：{text[:200]!r}")
    except Exception as e:
        check(f"--serve-mcp {name}", False, f"{type(e).__name__}: {e}")


def test_gui(exe: Path) -> None:
    log("")
    log("== 测试 2：GUI 身份（离屏）==")
    exe_dir = exe.resolve().parent
    seed = exe_dir / "knowledge" / "command_templates.csv"
    err_log = exe_dir / "logs" / "launcher_error.log"

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(k, None)
    env.setdefault("NO_PROXY", "127.0.0.1,localhost")

    t0 = time.time()
    try:
        proc = subprocess.Popen(
            [str(exe), "--gui", "--provider", "deepseek"],
            cwd=str(ROOT),  # 故意用项目根当 cwd：验证 BASE_DIR 取 exe 目录而非 cwd
            env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as e:
        check("GUI 进程拉起", False, f"{type(e).__name__}: {e}")
        return

    # 分段观察：8 秒后必须还活着（MCP 连接 + 初始化早已完成），活到 15 秒判胜
    alive_at = None
    for waited in range(1, 16):
        time.sleep(1)
        if proc.poll() is not None:
            break
        if waited == 8:
            alive_at = True
    alive = proc.poll() is None
    dt = time.time() - t0
    if alive:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    check("GUI 进程拉起并存活 ≥15s", alive, f"观察 {dt:.0f}s，退出码 {proc.returncode}")
    check("8 秒时仍存活（初始化已过 MCP 连接阶段）", bool(alive_at))
    check("种子资源已释放到 exe 旁", seed.is_file(), str(seed))
    check("未写 launcher_error.log", not err_log.is_file(),
          "存在启动期错误" if err_log.is_file() else "")


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "NetworkClaw" / "NetworkClaw.exe"
    log("==== 打包产物验证 ====")
    log(f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"exe：{exe}（存在={exe.is_file()}）")
    if not exe.is_file():
        log("exe 不存在，先跑 build_exe.ps1")
        return 2

    log("")
    log("== 测试 1：--serve-mcp 派发 ==")
    asyncio.run(test_serve_mcp(exe, "knowledge", None))
    asyncio.run(test_serve_mcp(exe, "knowledge",
                ("query_command_template",
                 {"intent": "配置OSPF宣告网段", "vendor": "Huawei", "device_type": "router"})))
    asyncio.run(test_serve_mcp(exe, "device-serial", ("classify_command",
                {"command": "display current-configuration"})))

    test_gui(exe)

    log("")
    log("==== 完成 ====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
