"""LLM 服务管理层：负责 llama-server 的启动、复用检测、健康检查与停止。

修复记录：
- 启动前先探测 8080 端口，若已有健康实例则直接复用，绝不重复拉起进程
- 健康检查改为循环重试（覆盖模型加载慢的情况），任何异常路径都会回收子进程
- 提供 kill_all_llama_servers() 用于清理历史残留进程

模型与端口配置集中在这里，其他模块统一通过 http://127.0.0.1:8080 调用。
"""
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_PATH = BASE_DIR / "logs" / "llama_server.log"

LLAMA_SERVER_PATH = r"C:\Users\yixixiawa\AppData\Local\Microsoft\WinGet\Packages\ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe\llama-server.exe"
# 模型源文件统一存放在项目 models/ 目录下
MODEL_PATH = str(BASE_DIR / "models" / "Qwen3.5-9B-Q4_K_M.gguf")
SERVER_PORT = 8080
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


def is_server_running(timeout: float = 3.0) -> bool:
    """探测 llama-server 是否已在目标端口提供正常服务"""
    try:
        r = requests.get(f"{BASE_URL}/v1/models", timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _terminate(proc: subprocess.Popen):
    """确保子进程被完全回收"""
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def start_llama_server():
    """启动 llama-server（单实例），返回进程对象；若已有实例在运行则返回 None 直接复用"""
    if is_server_running():
        print(f"检测到 llama-server 已在端口 {SERVER_PORT} 运行，直接复用（退出时不会关闭它）")
        return None

    cmd = [
        LLAMA_SERVER_PATH,
        "-m", MODEL_PATH,
        "--parallel", "1",
        "-ngl", "99",
        "-c", "4096",
        "-fa", "on",
        "--cache-type-k", "q4_0",
        "--cache-type-v", "q4_0",
        "--jinja",  # 启用模型自带聊天模板，OpenAI 风格工具调用（tools/tool_calls）依赖它
        "--host", "0.0.0.0",
        "--port", str(SERVER_PORT)
    ]

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(LOG_PATH, "w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=log_file,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    print(f"正在启动 llama-server（加载模型可能需要一些时间）...")

    deadline = time.time() + 120  # 最多等 2 分钟
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"llama-server 提前退出（退出码 {proc.returncode}），请查看日志：{LOG_PATH}"
                )
            if is_server_running():
                print("llama-server 已就绪")
                return proc
            time.sleep(2)
        raise RuntimeError("等待 llama-server 就绪超时（120 秒）")
    except Exception:
        # 任何失败路径都要回收刚拉起的进程，避免残留占用显存/内存
        _terminate(proc)
        raise
    finally:
        log_file.close()


def stop_llama_server(proc):
    """仅停止本进程自己拉起的 llama-server；复用的外部实例不动"""
    if proc is None:
        return
    _terminate(proc)


def kill_all_llama_servers():
    """强制结束所有 llama-server.exe（用于清理历史残留进程，请确认无其他项目在用）"""
    result = subprocess.run(
        ["taskkill", "/IM", "llama-server.exe", "/F"],
        capture_output=True, text=True
    )
    output = (result.stdout or "") + (result.stderr or "")
    if "成功" in output or "SUCCESS" in output.upper():
        print("已清理所有 llama-server 进程")
    else:
        print("没有需要清理的 llama-server 进程")


if __name__ == "__main__":
    # python -m core.llama_start kill  -> 清理所有残留进程
    # python -m core.llama_start       -> 前台运行 llama-server，回车退出
    if len(sys.argv) > 1 and sys.argv[1] == "kill":
        kill_all_llama_servers()
        sys.exit(0)

    proc = None
    try:
        proc = start_llama_server()
        if proc is not None:
            print("llama-server 正在运行...")
            input("按回车键退出并关闭 llama-server...")
    finally:
        stop_llama_server(proc)
        if proc is not None:
            print("llama-server 已关闭")
