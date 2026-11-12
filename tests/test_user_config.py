"""用户级配置持久化（%USERPROFILE%\\.networkclaw\\networkclaw.json）测试。

覆盖需求：自动建目录、标准 JSON、文件不存在/损坏容错、模型与密钥存取还原、
以及「读回后能被 providers 注册表用上」的集成路径。
"""
from __future__ import annotations

import json

import pytest

from core import user_config


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """把用户主目录指到临时目录，别往真实 ~/.networkclaw 写测试垃圾"""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    user_config.load(refresh=True)
    yield tmp_path
    user_config.load(refresh=True)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 路径与目录

def test_path_under_user_home(home):
    assert user_config.config_path() == home / ".networkclaw" / "networkclaw.json"


def test_save_creates_missing_directory(home):
    assert not (home / ".networkclaw").exists()

    path = user_config.set_active_model("deepseek-flash")

    assert path.is_file()
    assert path.parent.is_dir()
    assert _read(path)["active_model"] == "deepseek-flash"


# ---------------------------------------------------------------- 读写还原

def test_missing_file_returns_defaults(home):
    data = user_config.load(refresh=True)
    assert data["active_model"] == ""
    assert data["providers"] == {}
    assert not user_config.config_path().exists()   # 只读不写，不凭空建文件


def test_round_trip_model_and_key(home):
    user_config.set_active_model("deepseek-pro")
    path = user_config.set_api_key("deepseek-pro", "sk-test-123",
                                   api_key_env="DEEPSEEK_API_KEY")

    raw = _read(path)
    assert raw["active_model"] == "deepseek-pro"
    assert raw["providers"]["deepseek-pro"]["api_key"] == "sk-test-123"
    assert raw["providers"]["deepseek-pro"]["api_key_env"] == "DEEPSEEK_API_KEY"
    assert raw["updated"]

    # 模拟重启：清缓存重新从磁盘读
    user_config.load(refresh=True)
    assert user_config.get_active_model() == "deepseek-pro"
    assert user_config.get_api_key("deepseek-pro") == "sk-test-123"


def test_save_is_standard_json_utf8(home):
    path = user_config.set_model_override("deepseek-flash", "deepseek-flash-2026")
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "\n  " in text                       # indent=2，人工可读可编辑
    assert json.loads(text)["providers"]["deepseek-flash"]["model"] == "deepseek-flash-2026"


def test_clear_key_removes_entry(home):
    user_config.set_api_key("deepseek-flash", "sk-x", api_key_env="DEEPSEEK_API_KEY")
    user_config.set_api_key("deepseek-flash", "")
    user_config.load(refresh=True)
    assert user_config.get_api_key("deepseek-flash") == ""


# ---------------------------------------------------------------- 容错

def test_corrupt_file_falls_back_and_backs_up(home):
    directory = home / ".networkclaw"
    directory.mkdir(parents=True)
    bad = directory / "networkclaw.json"
    bad.write_text("{ this is not json", encoding="utf-8")

    data = user_config.load(refresh=True)

    assert data["active_model"] == ""
    assert data["providers"] == {}
    backups = list(directory.glob("networkclaw.json.bad-*"))
    assert len(backups) == 1                       # 坏文件留证，便于排查


def test_wrong_types_are_dropped_not_fatal(home):
    directory = home / ".networkclaw"
    directory.mkdir(parents=True)
    (directory / "networkclaw.json").write_text(
        json.dumps({"active_model": 123, "providers": {
            "deepseek-flash": {"api_key": 42, "model": ["x"]},
            "ok": {"api_key": "k", "model": "m"},
        }}), encoding="utf-8")

    data = user_config.load(refresh=True)

    assert data["active_model"] == ""              # 类型不对 → 丢弃
    assert "deepseek-flash" not in data["providers"]
    assert data["providers"]["ok"] == {"api_key": "k", "model": "m"}


def test_describe_never_leaks_key(home):
    user_config.set_active_model("deepseek-flash")
    user_config.set_api_key("deepseek-flash", "sk-super-secret", api_key_env="DEEPSEEK_API_KEY")

    text = user_config.describe()

    assert "sk-super-secret" not in text
    assert "密钥✓" in text


# ---------------------------------------------------------------- 环境变量同步

def _persist_key(key: str, provider: str = "deepseek-flash",
                 env_name: str = "DEEPSEEK_API_KEY") -> None:
    """直接落盘（不走 set_api_key，避免它顺手改进程环境变量干扰本组断言）"""
    data = user_config.load()
    providers = dict(data["providers"])
    providers[provider] = {"api_key": key, "api_key_env": env_name}
    data["providers"] = providers
    user_config.save(data)


def test_apply_to_environment_fills_missing(home, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    _persist_key("sk-from-file")

    applied = user_config.apply_to_environment()

    assert applied == {"DEEPSEEK_API_KEY": "deepseek-flash"}
    assert user_config.os.environ["DEEPSEEK_API_KEY"] == "sk-from-file"


def test_apply_to_environment_keeps_explicit_env(home, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    _persist_key("sk-from-file")

    user_config.apply_to_environment()

    assert user_config.os.environ["DEEPSEEK_API_KEY"] == "sk-from-env"


# ---------------------------------------------------------------- 与 providers 集成

def test_providers_restore_saved_model_and_key(home, monkeypatch, tmp_path):
    from core import providers

    # 隔离：不读项目 .env，也不让外部环境变量干扰
    monkeypatch.setattr(providers, "ENV_FILE", tmp_path / "missing.env")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("NETWORKCLAW_PROVIDER", raising=False)
    monkeypatch.delenv("NETWORKCLAW_DEFAULT_PROVIDER", raising=False)
    monkeypatch.setattr(providers, "CONFIG_FILE", tmp_path / "missing_llm.json")

    user_config.set_active_model("deepseek-pro")
    user_config.set_api_key("deepseek-pro", "sk-restored",
                            api_key_env="DEEPSEEK_API_KEY")

    table = providers.load_providers(refresh=True)

    assert providers.active_name() == "deepseek-pro"
    assert table["deepseek-pro"].api_key_value == "sk-restored"
    assert providers.get_provider().name == "deepseek-pro"
