"""图像识别层：让智能体看懂用户当前网络拓扑（截图 / 拓扑导出图）。

能力来源：
    llama.cpp 的多模态需要同时加载「主模型」与「视觉投影文件（mmproj）」：
        llama-server -m models/Qwen3.5-9B-Q4_K_M.gguf --mmproj models/mmproj-BF16.gguf
    因此 core/llama_start.py 增加了 --mmproj 参数；本模块负责：
        1. 自动探测项目内的 mmproj 文件（也可用环境变量 NETWORKCLAW_MMPROJ 指定）
        2. 把图片等比缩放后编码为 OpenAI 视觉格式（data URI），避免超长 base64 挤爆上下文
        3. 用「网络拓扑识读」专用提示词调用本地模型，输出结构化拓扑描述

为什么要在本地做：拓扑截图往往含内网设备名、IP 段、链路信息，走本地模型不外传更安全。

被 mcp_tools/vision_server.py（analyze_topology_image 工具）与 main.py（/image 命令）共用。
"""
import base64
import io
from pathlib import Path

import requests

from core.llama_start import (  # noqa: F401  (find_mmproj / mmproj_hint 在此转出，供 MCP 工具层使用)
    BASE_DIR,
    BASE_URL,
    find_mmproj,
    mmproj_hint,
    server_vision_state,
)

MODELS_DIR = BASE_DIR / "models"

# 图片处理限制
MAX_SIDE = 1280               # 长边上限（像素），太大会显著吃显存与上下文
JPEG_QUALITY = 88
MAX_IMAGE_MB = 20             # 单张图片体积上限

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}

# 拓扑识读专用系统提示词：要求结构化输出，便于后续直接生成配置
TOPOLOGY_SYSTEM_PROMPT = """你是资深网络工程师，正在阅读用户提供的网络拓扑图。
请仔细观察图中信息，按以下结构输出（信息不存在就写「图中未标注」，绝不要编造）：

1. 拓扑概览：设备总数、分层结构（核心/汇聚/接入、出口/内网）
2. 设备清单：逐台列出 —— 名称/标签、型号或厂商线索（如 S5700、AR 系列、Cisco IOS 风格图标）、
   设备角色（交换机/路由器/防火墙/PC/服务器）、若图中有 IP 则一并列出
3. 连接关系：逐条列出链路 —— 本端设备(接口) ↔ 对端设备(接口)，
   若标注了链路类型/带宽/网段请一并说明
4. IP 与网段：图中出现的所有 IP 地址、网段、VLAN ID
5. 值得注意的点：单点故障、环路、缺失的冗余链路、IP 冲突、未标注的接口等

最后附一句「可用于本工具的下一步」建议（例如：需要查询哪台设备的配置命令）。"""


# ---------------------------------------------------------------- 图片编码

def encode_image_data_uri(path: str | Path, max_side: int = MAX_SIDE,
                          quality: int = JPEG_QUALITY) -> tuple[str, dict]:
    """把图片缩放并编码为 data URI，返回 (data_uri, 元信息)"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"图片不存在：{p}")
    if not p.is_file():
        raise ValueError(f"不是文件：{p}")
    size_mb = p.stat().st_size / 1024 / 1024
    if size_mb > MAX_IMAGE_MB:
        raise ValueError(f"图片过大（{size_mb:.1f} MB > {MAX_IMAGE_MB} MB），请先压缩或裁剪")

    meta = {"path": str(p), "orig_mb": round(size_mb, 2)}

    try:
        from PIL import Image
    except ImportError:
        # 没有 Pillow 时退化为原图直传（可能体积较大）
        raw = p.read_bytes()
        meta.update({"width": None, "height": None, "resized": False,
                     "format": p.suffix.lstrip(".").lower()})
        return f"data:image/{meta['format']};base64,{base64.b64encode(raw).decode()}", meta

    with Image.open(p) as im:
        meta["width"], meta["height"] = im.size
        meta["format"] = (im.format or p.suffix.lstrip(".")).lower()
        w0, h0 = im.size
        im = im.convert("RGB")
        if max(w0, h0) > max_side:
            im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        meta["resized"] = (im.size != (w0, h0)) or meta["format"] not in ("jpeg", "jpg")
        meta["out_size"] = im.size
        data = buf.getvalue()

    meta["out_kb"] = round(len(data) / 1024, 1)
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}", meta


def build_user_content(text: str, images: list[str] | None = None):
    """构造 OpenAI 视觉格式的 user content（无图片时退化为纯文本）"""
    images = [str(i) for i in (images or []) if i]
    if not images:
        return text

    content: list[dict] = [{"type": "text", "text": text}]
    for img in images:
        uri, _ = encode_image_data_uri(img)
        content.append({"type": "image_url", "image_url": {"url": uri}})
    return content


# ---------------------------------------------------------------- 服务端就绪探测

def vision_status() -> dict:
    """判断视觉能力是否可用（委托给 core.llama_start 的服务实例探测）。

    返回 {"available": bool|None, "detail": str}
        True  已确认可用
        False 明确不可用（未加载 mmproj 或服务未启动）
        None  无法确定（服务在跑但没有可判读字段）——此时建议直接试一次
    """
    available, detail = server_vision_state()
    return {"available": available, "detail": detail}


# ---------------------------------------------------------------- 视觉问答

def describe_image(image_path: str | Path, question: str = "",
                   system_prompt: str = TOPOLOGY_SYSTEM_PROMPT,
                   show_thinking: bool = False, max_side: int = MAX_SIDE,
                   timeout: int = 600) -> str:
    """让本地多模态模型描述一张图片（默认按「网络拓扑识读」提示词处理）。

    Args:
        image_path: 图片路径
        question: 用户的具体问题；为空则按拓扑识读模板输出
        system_prompt: 系统提示词
        show_thinking: 是否打印模型思考过程
        max_side: 图片长边缩放上限
        timeout: 请求超时秒数

    Raises:
        FileNotFoundError / ValueError: 图片不存在或过大
        RuntimeError: 服务不可用或模型不支持图片
    """
    from core.llm_client import stream_chat  # 延迟导入，避免环状依赖

    uri, meta = encode_image_data_uri(image_path, max_side=max_side)
    ask = (question or "").strip() or "请识读这张网络拓扑图，按结构说明设备与链路关系。" + \
          "如果图中还有你无法确认的信息，请明确说明。"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": ask},
            {"type": "image_url", "image_url": {"url": uri}},
        ]},
    ]

    try:
        result = stream_chat(messages, tools=None, show_thinking=show_thinking,
                             show_answer=False, timeout=timeout)
    except requests.HTTPError as e:
        body = ""
        try:
            body = e.response.text[:300]
        except Exception:
            pass
        raise RuntimeError(
            f"视觉请求被服务端拒绝（HTTP {getattr(e.response, 'status_code', '?')}）：{body}\n"
            f"通常是 llama-server 未加载 mmproj。{mmproj_hint()}"
        ) from e
    except requests.RequestException as e:
        raise RuntimeError(f"无法连接 llama-server（{BASE_URL}）：{e}") from e

    if not result.content.strip():
        status = vision_status()
        raise RuntimeError(
            f"模型没有返回内容（视觉能力状态：{status['detail']}）。{mmproj_hint()}"
        )
    return result.content


def list_local_images(directory: str | Path | None = None, limit: int = 20) -> list[dict]:
    """列出可用的图片文件（帮助模型在用户没给全路径时找到拓扑图）"""
    dirs = []
    if directory:
        dirs.append(Path(directory))
    else:
        for name in ("Desktop", "Downloads", "Pictures", "Documents"):
            p = Path.home() / name
            if p.exists():
                dirs.append(p)
        dirs.append(BASE_DIR)

    out: list[dict] = []
    for d in dirs:
        if not d.exists():
            continue
        try:
            for f in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                    out.append({
                        "path": str(f),
                        "name": f.name,
                        "mb": round(f.stat().st_size / 1024 / 1024, 2),
                        "mtime": __import__("datetime").datetime.fromtimestamp(
                            f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
                    if len(out) >= limit:
                        return out
        except (PermissionError, OSError):
            continue
    return out
