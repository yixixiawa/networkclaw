"""模型提供方注册表（core/providers.py）与 localhost 代理豁免（core/net.py）。"""
import os

import pytest

from core import providers


def test_builtin_providers_present():
    table = providers.load_providers(refresh=True)
    for name in ("local", "deepseek-flash", "deepseek-pro"):
        assert name in table, f"内置提供方缺失：{name}（现有：{list(table)}）"


def test_legacy_aliases_map_to_v4_names():
    """旧名兼容：deepseek/deepseek-chat -> deepseek-flash；deepseek-reasoner -> deepseek-pro。"""
    assert providers.get_provider("deepseek").name == "deepseek-flash"
    assert providers.get_provider("deepseek-chat").name == "deepseek-flash"
    assert providers.get_provider("deepseek-reasoner").name == "deepseek-pro"


def test_case_insensitive_lookup():
    assert providers.get_provider("Local").name == "local"


def test_unknown_provider_raises_keyerror():
    with pytest.raises(KeyError):
        providers.get_provider("no-such-provider-xyz")


def test_cloud_provider_requires_api_key_shape():
    """云端提供方必须声明密钥来源（环境变量名），本地提供方无此要求。"""
    table = providers.load_providers()
    assert table["deepseek-flash"].api_key_env == "DEEPSEEK_API_KEY"
    assert table["local"].kind == "local"


def test_ensure_localhost_bypass_covers_loopback():
    """本机代理会劫持 127.0.0.1 -> NO_PROXY 必须包含回环地址（core/net.py）。"""
    from core.net import ensure_localhost_bypass

    saved = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
    for k in saved:
        os.environ.pop(k, None)
    try:
        ensure_localhost_bypass()
        joined = os.environ.get("NO_PROXY", "") + os.environ.get("no_proxy", "")
        assert "127.0.0.1" in joined
        assert "localhost" in joined
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
