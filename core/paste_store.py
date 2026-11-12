"""剪贴板图片落盘：把内存里的图片字节写成文件，供输入框以「文件名」形式引用。

为什么需要落盘而不是内联：
    - 附件栏、worker、识图（vision）走的都是**文件路径**，直接塞 QImage 会多出一条
      数据通路，且打包后跨线程传像素没有收益；
    - 落盘后同一张图可以反复粘贴/引用，会话记录里留下的也是可追溯的路径。

命名规则：``paste-<YYYYmmdd-HHMMSS>-<内容摘要8位>.<后缀>``
    - 时间戳让人一眼看出是什么时候截的图；
    - 内容摘要保证**同一张图重复粘贴复用同一个文件**（不堆副本，附件栏也不会
      出现两个同名条目）；
    - 全是 ASCII，避免中文路径在 MCP 子进程 / 打包环境里被转码搞坏。

本模块刻意不 import PyQt6：它的入参是 bytes，可脱离 Qt 单测（CI 不装 PyQt6）。
把 QImage 编码成 PNG 的那一步在 GUI 层（gui/main_window.py:InputEdit）。
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path

from core.paths import BASE_DIR

#: 粘贴图片的存放目录（运行时产物，已 .gitignore）
PASTE_DIR = "data/pasted_images"
#: 文件名前缀
PASTE_PREFIX = "paste"

#: 允许的图片后缀（与 core/vision.IMAGE_EXTS 对齐，只用于校验落盘后缀）
_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}


def paste_dir() -> Path:
    """粘贴图片目录（不存在时按需创建由 save_bytes 负责）"""
    return BASE_DIR / "data" / "pasted_images"


def normalize_suffix(suffix: str) -> str:
    """把后缀规范成 ``.png`` 这种形式；不认识的落到 .png（我们只写 PNG）"""
    s = (suffix or "").strip().lower()
    if not s:
        return ".png"
    if not s.startswith("."):
        s = "." + s
    return s if s in _ALLOWED_SUFFIXES else ".png"


def digest8(data: bytes) -> str:
    """内容摘要前 8 位（用于「同图不重复落盘」）"""
    return hashlib.sha1(data).hexdigest()[:8]


def find_existing(directory: Path, digest: str, suffix: str) -> Path | None:
    """目录里是否已有同内容文件（重复粘贴直接复用）"""
    for p in directory.glob(f"{PASTE_PREFIX}-*-{digest}{suffix}"):
        if p.is_file():
            return p
    return None


def save_bytes(data: bytes, *, suffix: str = ".png", directory: Path | None = None,
               now: datetime | None = None) -> Path:
    """把图片字节写成文件并返回路径。

    - 空数据 → ValueError（调用方应跳过而不是造一个 0 字节「图片」）
    - 同内容已存在 → 直接返回旧路径（幂等）
    - 目录不可写 → 让 OSError 冒到调用方（GUI 里降级成提示，不崩）
    """
    if not data:
        raise ValueError("图片内容为空")

    suffix = normalize_suffix(suffix)
    target_dir = Path(directory) if directory is not None else paste_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    digest = digest8(data)
    existing = find_existing(target_dir, digest, suffix)
    if existing is not None:
        return existing

    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    path = target_dir / f"{PASTE_PREFIX}-{stamp}-{digest}{suffix}"

    # 原子写：先写临时文件再 replace（进程被杀也不会留下半张图）。
    # 临时名带 pid，两个实例同时粘同一张图时不会互相写坏对方的中转文件。
    tmp = target_dir / f"{path.name}.{os.getpid()}.tmp"
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return path
