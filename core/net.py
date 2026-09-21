"""本地网络环境修正：确保对 127.0.0.1 / localhost 的请求绕过系统代理。

为什么需要：
    开发机上常驻着本地代理（如 Clash / v2ray，监听 127.0.0.1:7890 之类），
    系统会设置 HTTP_PROXY/HTTPS_PROXY。requests、httpx 等库**默认对 localhost 也走代理**，
    于是 `http://127.0.0.1:8080`（llama-server）与 `http://127.0.0.1:11434`（Ollama）
    会被丢给代理，返回 502/连接失败，表现为「服务明明在跑却连不上」。

    本项目所有对 LLM / Embedding 的调用都是本机回环地址，因此在导入时统一把
    127.0.0.1 / localhost / ::1 追加进 NO_PROXY，彻底避免这类误伤。

被 core/llama_start.py 与 core/ollama_interface.py 在模块导入时调用（其余模块间接受益）。
"""
import os

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def ensure_localhost_bypass() -> str:
    """把本机回环地址加入 NO_PROXY / no_proxy（已存在则不重复添加），返回最终值"""
    current = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    parts = [p.strip() for p in current.split(",") if p.strip()]

    changed = False
    for host in LOCAL_HOSTS:
        if host not in parts:
            parts.append(host)
            changed = True

    value = ",".join(parts)
    if changed or not current:
        # requests/httpx/urllib 会读这两个变量，大小写都写一份更稳妥
        os.environ["NO_PROXY"] = value
        os.environ["no_proxy"] = value
    return value


# 导入即生效：本模块被 core 层引用时自动完成修正
LOCAL_NO_PROXY = ensure_localhost_bypass()
