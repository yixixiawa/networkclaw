"""备用提供方（智谱 GLM / Kimi）与「备用 Key + 自动降级」的测试。

覆盖需求：
    1. 两个备用提供方按现有 Provider 接口注册（端点/模型/密钥变量/能力画像）；
    2. 备用 Key 与主 Key 同等配置（环境变量 → 用户配置 → config/llm.json），
       且「主 Key 被拒 → 换备用 Key」只换密钥、不换模型；
    3. 主提供方不可用 → 按 fallback 链自动切到备用提供方；
    4. 已经流给用户的内容不被重复（中途失败不重来）；
    5. 可关闭降级（NETWORKCLAW_NO_FALLBACK / allow_fallback=False）。
"""
from __future__ import annotations

import json

import pytest

from core import llm_client as llm
from core import providers, user_config

KEY_ENVS = (
    "DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_BACKUP",
    "ZHIPU_API_KEY", "ZHIPU_API_KEY_BACKUP", "GLM_API_KEY", "GLM_API_KEY_BACKUP",
    "MOONSHOT_API_KEY", "MOONSHOT_API_KEY_BACKUP", "KIMI_API_KEY", "KIMI_API_KEY_BACKUP",
    "NETWORKCLAW_NO_FALLBACK", "NETWORKCLAW_PROVIDER", "NETWORKCLAW_DEFAULT_PROVIDER",
    "NETWORKCLAW_LOCAL_BASE_URL", "NETWORKCLAW_LOCAL_MODEL",
)


@pytest.fixture()
def clean(tmp_path, monkeypatch):
    """密封的注册表：不读真实 config/llm.json、.env 与 ~/.networkclaw。

    否则开发者机器上真实的密钥会让「未配置 → 走降级」这类断言随机失败。
    """
    monkeypatch.setattr(providers, "CONFIG_FILE", tmp_path / "no-such-llm.json")
    monkeypatch.setattr(providers, "ENV_FILE", tmp_path / "no-such.env")
    monkeypatch.setattr(user_config, "load",
                        lambda refresh=False: {"version": 1, "active_model": "",
                                               "providers": {}, "updated": ""})
    monkeypatch.setattr(user_config, "apply_to_environment", lambda: {})
    for name in KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    providers._providers = None
    providers._active = None
    yield providers
    providers._providers = None
    providers._active = None


# ---------------------------------------------------------------- 注册

def test_backup_providers_registered_with_same_interface(clean):
    table = clean.load_providers(refresh=True)

    glm = table["glm-4.6"]
    assert glm.base_url.rstrip("/") == "https://open.bigmodel.cn/api/paas/v4"
    assert glm.model == "glm-4.6" and glm.kind == "cloud"
    assert glm.api_key_env == "ZHIPU_API_KEY"
    assert glm.api_key_alt_env == "ZHIPU_API_KEY_BACKUP"
    assert glm.supports_tools and glm.supports_thinking
    assert not glm.supports_vision          # 文本模型：看图要走视觉桥接

    kimi = table["kimi-k2.5"]
    assert kimi.base_url.rstrip("/") == "https://api.moonshot.cn/v1"
    assert kimi.model == "kimi-k2.5"
    assert kimi.api_key_env == "MOONSHOT_API_KEY"
    assert kimi.api_key_alt_env == "MOONSHOT_API_KEY_BACKUP"
    assert kimi.supports_tools and kimi.supports_vision


def test_backup_providers_are_in_primary_fallback_chain(clean):
    """主提供方默认就把这两个列为备用（否则「自动切换」无从谈起）。"""
    table = clean.load_providers(refresh=True)
    assert "glm-4.6" in table["deepseek-flash"].fallback
    assert "kimi-k2.5" in table["deepseek-flash"].fallback
    assert "kimi-k2.5" in table["glm-4.6"].fallback


def test_backup_provider_aliases(clean):
    assert clean.get_provider("glm").name == "glm-4.6"
    assert clean.get_provider("zhipu").name == "glm-4.6"
    assert clean.get_provider("kimi").name == "kimi-k2.5"
    assert clean.get_provider("moonshot").name == "kimi-k2.5"


def test_shipped_config_matches_builtin_names():
    """仓库里的 config/llm.json 声明的提供方必须都能对上内置注册表（防漂移）。"""
    from core.paths import BASE_DIR

    data = json.loads((BASE_DIR / "config" / "llm.json").read_text(encoding="utf-8"))
    builtin = set(providers._builtin())
    declared = set((data.get("providers") or {}))
    assert declared <= builtin, f"配置里有内置不认识的提供方：{declared - builtin}"
    assert {"glm-4.6", "kimi-k2.5"} <= declared


# ---------------------------------------------------------------- 备用 Key

def test_alt_key_alone_makes_provider_configured(clean, monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY_BACKUP", "sk-alt")
    clean.load_providers(refresh=True)

    prov = clean.get_provider("glm-4.6")
    assert prov.api_key_value == ""
    assert prov.api_key_alt_value == "sk-alt"
    assert prov.is_configured
    assert [slot for slot, _ in prov.key_candidates()] == ["备用"]
    assert "备用" in prov.status_line()


def test_alt_key_equal_to_primary_is_deduped(clean, monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-same")
    monkeypatch.setenv("ZHIPU_API_KEY_BACKUP", "sk-same")
    clean.load_providers(refresh=True)

    candidates = clean.get_provider("glm-4.6").key_candidates()
    assert len(candidates) == 1 and candidates[0][0] == "主"


def test_fallback_chain_skips_providers_without_key(clean, monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi")
    clean.load_providers(refresh=True)

    names = [p.name for p in clean.fallback_chain("local")]
    assert names == ["kimi-k2.5"]        # deepseek/glm 没 Key，不进队列


def test_fallback_chain_is_cycle_safe(clean, monkeypatch):
    for env in ("DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "MOONSHOT_API_KEY"):
        monkeypatch.setenv(env, "sk-x")
    clean.load_providers(refresh=True)

    names = [p.name for p in clean.fallback_chain("local")]
    assert names == ["deepseek-flash", "glm-4.6", "kimi-k2.5"]
    assert len(names) == len(set(names))
    assert "local" not in names


def test_fallback_disabled_by_env(clean, monkeypatch):
    for env in ("DEEPSEEK_API_KEY", "ZHIPU_API_KEY"):
        monkeypatch.setenv(env, "sk-x")
    monkeypatch.setenv("NETWORKCLAW_NO_FALLBACK", "1")
    clean.load_providers(refresh=True)

    assert clean.fallback_enabled() is False
    assert clean.fallback_chain("deepseek-flash") == []


# ---------------------------------------------------------------- 流式降级

class _Resp:
    """假的流式响应（requests 的上下文管理器 + iter_lines 接口）"""

    def __init__(self, text: str = "答"):
        self._lines = [
            ("data: " + json.dumps({"choices": [{"delta": {"content": text}}]})).encode(),
            b"data: [DONE]",
        ]

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _BrokenResp(_Resp):
    """吐了半句就断线：用来验证「已经流出去的内容不会重来」"""

    def iter_lines(self, decode_unicode=False):
        yield ("data: " + json.dumps(
            {"choices": [{"delta": {"content": "半"}}]})).encode()
        raise llm.ProviderError("连接中断", retryable=True)


def _install_post(monkeypatch, *, dead_keys=(), broken=()):
    """把 _post_stream 换成本地假实现，记录 (提供方, 用到的密钥)。

    dead_keys 里的密钥 → 抛 401；broken 里的提供方 → 吐半句后断线。
    """
    seen: list[tuple[str, str]] = []

    def fake(provider, payload, timeout):
        seen.append((provider.name, provider.api_key_value))
        if provider.api_key_value in dead_keys:
            raise llm.ProviderError(f"{provider.name}：鉴权失败（HTTP 401）",
                                    status=401, auth=True)
        if provider.name in broken:
            return _BrokenResp()
        return _Resp(f"来自{provider.name}")

    monkeypatch.setattr(llm, "_post_stream", fake)
    return seen


def test_primary_key_rejected_switches_to_backup_key(clean, monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-dead")
    monkeypatch.setenv("ZHIPU_API_KEY_BACKUP", "sk-alt-good")
    clean.load_providers(refresh=True)
    seen = _install_post(monkeypatch, dead_keys=("sk-dead",))

    res = llm.stream_chat([{"role": "user", "content": "hi"}],
                          provider="glm-4.6", show_thinking=False, show_answer=False)

    assert res.provider == "glm-4.6" and res.key_slot == "备用"
    assert res.fallback_from == ""                 # 只换 Key，不算换提供方
    assert seen == [("glm-4.6", "sk-dead"), ("glm-4.6", "sk-alt-good")]


def test_primary_provider_failure_switches_to_backup_provider(clean, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dead")
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi")
    clean.load_providers(refresh=True)
    seen = _install_post(monkeypatch, dead_keys=("sk-dead",))

    res = llm.stream_chat([{"role": "user", "content": "hi"}],
                          provider="deepseek-flash",
                          show_thinking=False, show_answer=False)

    assert res.provider == "kimi-k2.5"
    assert res.fallback_from == "deepseek-flash"
    assert [n for n, _ in seen] == ["deepseek-flash", "kimi-k2.5"]


def test_unconfigured_primary_falls_back_without_failing(clean, monkeypatch):
    """主提供方连 Key 都没有（用户只配了备用那家）→ 直接走备用。"""
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-glm")
    clean.load_providers(refresh=True)
    seen = _install_post(monkeypatch)

    res = llm.stream_chat([{"role": "user", "content": "hi"}],
                          provider="deepseek-flash",
                          show_thinking=False, show_answer=False)

    assert res.provider == "glm-4.6" and res.fallback_from == "deepseek-flash"
    assert [n for n, _ in seen] == ["glm-4.6"]


def test_all_paths_fail_reports_every_reason(clean, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dead")
    monkeypatch.setenv("ZHIPU_API_KEY", "sk-dead")
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-dead")
    clean.load_providers(refresh=True)
    _install_post(monkeypatch, dead_keys=("sk-dead",))

    with pytest.raises(llm.ProviderError) as ei:
        llm.stream_chat([{"role": "user", "content": "hi"}],
                        provider="deepseek-flash",
                        show_thinking=False, show_answer=False)

    msg = str(ei.value)
    assert "依次尝试" in msg
    assert "deepseek-flash" in msg and "kimi-k2.5" in msg
    assert "鉴权失败" in msg


def test_no_retry_once_text_already_streamed(clean, monkeypatch):
    """已经吐给用户半句 → 不允许换提供方重来（否则回答会拼接错乱）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deep")
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi")
    clean.load_providers(refresh=True)
    seen = _install_post(monkeypatch, broken=("deepseek-flash",))
    shown: list[str] = []

    with pytest.raises(llm.ProviderError):
        llm.stream_chat([{"role": "user", "content": "hi"}],
                        provider="deepseek-flash",
                        show_thinking=False, show_answer=True,
                        on_answer=shown.append)

    assert shown == ["半"]                                # 用户已经看到了这半句
    assert [n for n, _ in seen] == ["deepseek-flash"]     # 没有偷偷换家重答


def test_allow_fallback_false_is_strict(clean, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dead")
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi")
    clean.load_providers(refresh=True)
    seen = _install_post(monkeypatch, dead_keys=("sk-dead",))

    with pytest.raises(llm.ProviderError):
        llm.stream_chat([{"role": "user", "content": "hi"}],
                        provider="deepseek-flash", allow_fallback=False,
                        show_thinking=False, show_answer=False)

    assert [n for n, _ in seen] == ["deepseek-flash"]


def test_payload_variants_drop_vendor_specific_extra_body(clean):
    """厂商私有字段（thinking 等）不被接受时要能剥掉重试，而不是判整个提供方不可用。"""
    prov = clean.get_provider("glm-4.6")
    payload = llm._build_payload([{"role": "user", "content": "x"}], prov, None, 0.1, [])

    variants = llm._payload_variants(payload, prov)

    assert "thinking" in variants[0]
    assert "thinking" not in variants[-1]


# ---------------------------------------------------------------- 持久化

@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    user_config.load(refresh=True)
    yield tmp_path
    user_config.load(refresh=True)


def test_alt_key_round_trip(home):
    path = user_config.set_api_key_alt("glm-4.6", "sk-alt-1",
                                       api_key_alt_env="ZHIPU_API_KEY_BACKUP")

    raw = json.loads(path.read_text(encoding="utf-8"))
    entry = raw["providers"]["glm-4.6"]
    assert entry["api_key_alt"] == "sk-alt-1"
    assert entry["api_key_alt_env"] == "ZHIPU_API_KEY_BACKUP"
    assert entry["api_key_env"] == "ZHIPU_API_KEY"      # 从注册表补齐

    user_config.load(refresh=True)
    assert user_config.get_api_key_alt("glm-4.6") == "sk-alt-1"

    user_config.set_api_key_alt("glm-4.6", "")
    assert user_config.get_api_key_alt("glm-4.6") == ""


def test_alt_key_applied_to_distinct_env(home, monkeypatch):
    user_config.set_api_key("glm-4.6", "sk-main", api_key_env="ZHIPU_API_KEY")
    user_config.set_api_key_alt("glm-4.6", "sk-alt", api_key_alt_env="ZHIPU_API_KEY_BACKUP")
    # 保存时已同步进环境变量；模拟「新进程启动」：先清空再看 apply_to_environment 是否补回
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY_BACKUP", raising=False)

    applied = user_config.apply_to_environment()

    assert applied["ZHIPU_API_KEY_BACKUP"] == "glm-4.6"
    assert user_config.os.environ["ZHIPU_API_KEY_BACKUP"] == "sk-alt"
    assert user_config.os.environ["ZHIPU_API_KEY"] == "sk-main"
