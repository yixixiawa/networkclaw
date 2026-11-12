"""剪贴板图片落盘（core/paste_store）：命名、去重、原子写、异常边界。

纯字节接口，不需要 PyQt6 —— 这样可以进 CI。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from core import paste_store


def test_save_bytes_writes_into_given_dir(tmp_path):
    data = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    path = paste_store.save_bytes(data, directory=tmp_path,
                                  now=datetime(2026, 11, 1, 18, 51, 5))

    assert path.is_file()
    assert path.read_bytes() == data
    # 命名规则：paste-<时间戳>-<内容摘要8位>.png
    assert path.name == f"paste-20261101-185105-{paste_store.digest8(data)}.png"
    # 不留 .tmp 半成品
    assert not list(tmp_path.glob("*.tmp"))


def test_same_image_pasted_twice_reuses_one_file(tmp_path):
    data = b"same-bytes"

    first = paste_store.save_bytes(data, directory=tmp_path)
    second = paste_store.save_bytes(data, directory=tmp_path)

    assert first == second
    assert len(list(tmp_path.iterdir())) == 1


def test_different_images_get_different_files(tmp_path):
    a = paste_store.save_bytes(b"image-a", directory=tmp_path)
    b = paste_store.save_bytes(b"image-b", directory=tmp_path)

    assert a != b
    assert a.read_bytes() == b"image-a"


def test_suffix_normalized_and_unknown_falls_back_to_png(tmp_path):
    assert paste_store.normalize_suffix("PNG") == ".png"
    assert paste_store.normalize_suffix("jpg") == ".jpg"
    assert paste_store.normalize_suffix(".exe") == ".png"
    assert paste_store.normalize_suffix("") == ".png"

    path = paste_store.save_bytes(b"x", suffix="jpg", directory=tmp_path)
    assert path.suffix == ".jpg"


def test_empty_bytes_rejected(tmp_path):
    with pytest.raises(ValueError):
        paste_store.save_bytes(b"", directory=tmp_path)
    assert not list(tmp_path.iterdir())


def test_paste_dir_under_data():
    path = paste_store.paste_dir()
    assert path.parent.name == "data"
    assert path.name == "pasted_images"
