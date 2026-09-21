"""LLM 服务管理层：负责 llama-server 的启动、复用检测、健康检查与停止。

修复记录：
- 启动前先探测 8080 端口，若已有健康实例则直接复用，绝不重复拉起进程
- 健康检查改为循环重试（覆盖模型加载慢的情况），任何异常路径都会回收子进程
- 提供 kill_all_llama_servers() 用于清理历史残留进程

多模态（图像识别）：
- 视觉能力靠「主模型 + 视觉投影文件 mmproj」同时加载，即 llama-server 的 --mmproj 参数
- mmproj 文件自动探测 models/ 目录（也可用 --mmproj <路径> 或环境变量 NETWORKCLAW_MMPROJ 指定）
- 复用外部实例时会检查其是否加载了 mmproj：请求视觉但实例不支持时给出明确提示，而不是静默失败

模型与端口配置集中在这里，其他模块统一通过 http://127.0.0.1:8080 调用。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_PATH = BASE_DIR / "logs" / "llama_server.log"

LLAMA_SERVER_PATH = r"C:\Users\yixixiawa\AppData\Local\Microsoft\WinGet\Packages\ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe\llama-server.exe"
# 模型源文件统一存放在项目 models/ 目录下
MODELS_DIR = BASE_DIR / "models"
MODEL_PATH = str(MODELS_DIR / "Qwen3.5-9B-Q4_K_M.gguf")
SERVER_PORT = 8080
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"

MMPROJ_DOWNLOAD_URL = ("https://www.modelscope.cn/models/unsloth/Qwen3.5-9B-GGUF/"
                       "resolve/master/mmproj-BF16.gguf")


# ---------------------------------------------------------------- mmproj 探测

def find_mmproj(explicit: str | Path | None = None) -> Path | None:
    """定位视觉投影文件（mmproj）。

    优先级：显式传入 > 环境变量 NETWORKCLAW_MMPROJ > models/ 下的 *mmproj*.gguf
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("NETWORKCLAW_MMPROJ")
    if env:
        candidates.append(Path(env))
    if MODELS_DIR.exists():
        candidates += sorted(MODELS_DIR.glob("*mmproj*.gguf"))

    seen = set()
    for c in candidates:
        key = str(c).lower()
        if key in seen:
            continue
        seen.add(key)
        if c.is_file():
            return c
    return None


def mmproj_hint() -> str:
    """未找到 mmproj 时给用户的可执行指引"""
    found = find_mmproj()
    if found:
        return f"已找到视觉投影文件：{found}"
    return (
        "未找到视觉投影文件（mmproj）。请把与本模型配套的 mmproj 放进 models/ 目录后重试：\n"
        f"  {MODELS_DIR / 'mmproj-BF16.gguf'}\n"
        f"来源（与 Qwen3.5-9B-Q4_K_M.gguf 同一仓库）：{MMPROJ_DOWNLOAD_URL}\n"
        "程序会自动探测 models/ 下的 *mmproj*.gguf；也可用 --mmproj <路径> "
        "或环境变量 NETWORKCLAW_MMPROJ 显式指定。"
    )


# ---------------------------------------------------------------- 服务探测

def is_server_running(timeout: float = 3.0) -> bool:
    """探测 llama-server 是否已在目标端口提供正常服务"""
    try:
        r = requests.get(f"{BASE_URL}/v1/models", timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def server_props(timeout: float = 5.0) -> dict:
    """读取 llama-server 的 /props（用于判断该实例是否加载了视觉投影）"""
    try:
        r = requests.get(f"{BASE_URL}/props", timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def server_vision_state() -> tuple[bool | None, str]:
    """判断当前运行的实例是否具备视觉能力。

    Returns:
        (available, detail)
            True  已确认可用
            False 明确不可用（服务没跑）
            None  无法确定（没有可判读字段）——建议直接试一次识图
    """
    props = server_props()
    if not props:
        return False, "llama-server 未运行或 /props 不可用"

    blob = json.dumps(props, ensure_ascii=False).lower()
    hit = next((k for k in ("mmproj", "vision", "modalit", "image") if k in blob), None)
    if hit:
        return True, f"/props 中存在视觉相关字段（{hit}）"

    # 退一步：若实例是我们自己拉起的，可从启动日志确认
    try:
        if LOG_PATH.exists():
            tail = LOG_PATH.read_text(encoding="utf-8", errors="ignore").lower()[-20000:]
            if "mmproj" in tail:
                return True, "启动日志中有 mmproj 加载记录"
    except Exception:
        pass
    return None, "服务在运行，但无法从 /props 判断是否加载了 mmproj"


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


def start_llama_server(mmproj: str | None = None, require_vision: bool = False):
    """启动 llama-server（单实例），返回进程对象；若已有实例在运行则返回 None 直接复用。

    Args:
        mmproj: 视觉投影文件路径；传 "auto"/None 时自动探测 models/ 目录
        require_vision: 是否要求具备图像识别能力。为 True 时会校验 mmproj 是否存在、
                并检查已运行实例是否加载了视觉投影，避免「以为能识图其实不能」。
    """
    mmproj_path = find_mmproj(mmproj if mmproj and mmproj != "auto" else None)
    if require_vision and mmproj_path is None:
        raise RuntimeError("需要图像识别能力，但" + mmproj_hint())

    if is_server_running():
        if require_vision:
            state, detail = server_vision_state()
            if state is False or state is None:
                print("\n[警告] 端口 8080 上已有 llama-server 实例，但无法确认其加载了 mmproj"
                      f"（{detail}）。若识图失败，请执行 `python -m core.llama_start kill` "
                      "清理后重新启动。")
            else:
                print(f"检测到已在运行的 llama-server 支持图像识别（{detail}），直接复用")
        else:
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
    if mmproj_path is not None:
        # 多模态：加载视觉投影文件后，chat/completions 才接受 image_url 内容块
        cmd += ["--mmproj", str(mmproj_path)]

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(LOG_PATH, "w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=log_file,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    print("正在启动 llama-server（加载模型可能需要一些时间）...")
    if mmproj_path is not None:
        print(f"已启用图像识别（--mmproj {mmproj_path.name}）")
    else:
        print("未加载 mmproj，图像识别不可用（可用 --mmproj 指定视觉投影文件）")

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
    # python -m core.llama_start kill          -> 清理所有残留进程
    # python -m core.llama_start mmproj        -> 查看 mmproj 探测结果
    # python -m core.llama_start               -> 前台运行 llama-server，回车退出
    if len(sys.argv) > 1 and sys.argv[1] == "kill":
        kill_all_llama_servers()
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "mmproj":
        found = find_mmproj()
        print(f"主模型：{MODEL_PATH}（{'存在' if Path(MODEL_PATH).exists() else '缺失'}）")
        print(f"mmproj：{found}" if found else mmproj_hint())
        if is_server_running():
            state, detail = server_vision_state()
            print(f"运行中实例的视觉状态：{state} —— {detail}")
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
