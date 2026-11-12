"""用户级配置持久化：`%USERPROFILE%\\.networkclaw\\networkclaw.json`。

存什么：
    · 模型：当前激活的提供方（active_model），以及可选的自定义模型名覆盖；
    · 密钥：按提供方分别保存（providers.<name>.api_key / api_key_alt），并记住它的
      环境变量名（api_key_env / api_key_alt_env），读取时同步进进程环境变量——既有的
      core/providers.py 与 core/llm_client.py 无需改动即可用上持久化的密钥。

几条硬约定（踩过坑才写下来）：
    1. 目录不存在自动创建（`~/.networkclaw`），首次保存即建；
    2. 标准 JSON：UTF-8、indent=2、ensure_ascii=False（中文可读，便于用户手工编辑）；
    3. 原子写：先写 `.tmp` 再 `os.replace`，程序被杀不会留下半个文件；
    4. 文件不存在 / 内容损坏 / 字段类型不对 → 一律返回默认结构并**继续可用**，
       绝不因为配置坏了让程序起不来（坏文件顺手备份成 `.bad-<时间>` 便于排查）；
    5. 密钥不落日志：describe()/报错信息都只显示「已设置/未设置」。

为什么不用项目里的 .env：那要求用户能找到项目目录、且密钥会跟着仓库走。
用户级目录的文件属于「这台机器的这个用户」，与仓库无关，也不会被误提交。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from threading import Lock

#: 目录名固定：%USERPROFILE%\.networkclaw
DIR_NAME = ".networkclaw"
FILE_NAME = "networkclaw.json"
SCHEMA_VERSION = 1

_LOCK = Lock()
_cache: dict | None = None


def user_home() -> Path:
    """当前用户主目录（Windows 用 USERPROFILE，其它平台退回 HOME/~）"""
    for key in ("USERPROFILE", "HOME"):
        value = os.environ.get(key)
        if value:
            return Path(value)
    return Path.home()


def user_dir() -> Path:
    return user_home() / DIR_NAME


def config_path() -> Path:
    return user_dir() / FILE_NAME


# ---------------------------------------------------------------- 归一化

def _default() -> dict:
    return {
        "version": SCHEMA_VERSION,
        "active_model": "",
        "providers": {},
        "updated": "",
    }


def _normalize(data: object) -> dict:
    """把任意读到的内容整理成合法结构（类型不对就丢弃该字段，不抛异常）"""
    out = _default()
    if not isinstance(data, dict):
        return out
    if isinstance(data.get("active_model"), str):
        out["active_model"] = data["active_model"].strip()
    providers = data.get("providers")
    if isinstance(providers, dict):
        for name, conf in providers.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(conf, dict):
                continue
            entry: dict = {}
            key = conf.get("api_key")
            if isinstance(key, str):
                entry["api_key"] = key.strip()
            alt = conf.get("api_key_alt")
            if isinstance(alt, str):
                entry["api_key_alt"] = alt.strip()
            model = conf.get("model")
            if isinstance(model, str) and model.strip():
                entry["model"] = model.strip()
            env = conf.get("api_key_env")
            if isinstance(env, str) and env.strip():
                entry["api_key_env"] = env.strip()
            alt_env = conf.get("api_key_alt_env")
            if isinstance(alt_env, str) and alt_env.strip():
                entry["api_key_alt_env"] = alt_env.strip()
            if entry:
                out["providers"][name.strip()] = entry
    if isinstance(data.get("updated"), str):
        out["updated"] = data["updated"]
    return out


# ---------------------------------------------------------------- 读写

def load(refresh: bool = False) -> dict:
    """读取配置；文件不存在/损坏都返回默认结构（并缓存，refresh=True 强制重读）"""
    global _cache
    if _cache is not None and not refresh:
        return _cache
    path = config_path()
    if not path.is_file():
        _cache = _default()
        return _cache
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        _cache = _normalize(data)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        # 坏文件留证但不阻断：备份一份，然后按默认配置继续跑
        try:
            backup = path.with_name(f"{path.name}.bad-{datetime.now():%Y%m%d-%H%M%S}")
            path.replace(backup)
        except OSError:
            pass
        _cache = _default()
    return _cache


def save(data: dict) -> Path:
    """整篇保存（自动建目录、原子写、标准 JSON），返回文件路径"""
    global _cache
    payload = _normalize(data)
    payload["version"] = SCHEMA_VERSION
    payload["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with _LOCK:
        tmp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=path.parent,
                    prefix=f".{path.name}.", suffix=".tmp", delete=False) as tmp:
                tmp.write(text)
                tmp_name = tmp.name
            os.replace(tmp_name, path)
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass
    try:
        os.chmod(path, 0o600)   # POSIX 上顺手收紧权限；Windows 忽略
    except OSError:
        pass
    _cache = payload
    return path


def update(**changes) -> Path:
    """基于当前内容改几个顶层字段后保存（providers 之类由专用函数处理）"""
    data = dict(load())
    for key, value in changes.items():
        if value is not None:
            data[key] = value
    return save(data)


# ---------------------------------------------------------------- 模型

def get_active_model() -> str:
    """持久化的激活提供方名（未设置返回空串）"""
    return str(load().get("active_model") or "")


def set_active_model(name: str) -> Path:
    """记住当前使用的模型提供方（GUI 下拉框切换 / CLI /model 时调用）"""
    return update(active_model=str(name or "").strip())


def get_model_override(provider: str) -> str:
    """某提供方的模型名覆盖（未设置返回空串）"""
    return str((load()["providers"].get(provider) or {}).get("model") or "")


def set_model_override(provider: str, model: str) -> Path:
    """记住某提供方实际使用的模型名（比如换成本地另一个 gguf）"""
    data = load()
    providers = dict(data["providers"])
    entry = dict(providers.get(provider) or {})
    if model:
        entry["model"] = str(model).strip()
    else:
        entry.pop("model", None)
    if entry:
        providers[provider] = entry
    else:
        providers.pop(provider, None)
    data["providers"] = providers
    return save(data)


# ---------------------------------------------------------------- 密钥

def get_api_key(provider: str = "deepseek-flash") -> str:
    """取某提供方保存的主密钥（未设置返回空串）"""
    entry = load()["providers"].get(provider) or {}
    return str(entry.get("api_key") or "")


def get_api_key_alt(provider: str = "deepseek-flash") -> str:
    """取某提供方保存的备用密钥（未设置返回空串）"""
    entry = load()["providers"].get(provider) or {}
    return str(entry.get("api_key_alt") or "")


def set_api_key(provider: str, key: str, api_key_env: str = "") -> Path:
    """保存某提供方的密钥；同时写入进程环境变量，本进程立即生效。

    api_key_env 留空时尝试从 provider 注册表查（查不到就只存文件）。
    """
    provider = str(provider or "").strip()
    data = load()
    providers = dict(data["providers"])
    entry = dict(providers.get(provider) or {})
    if key:
        entry["api_key"] = str(key).strip()
    else:
        entry.pop("api_key", None)
    env_name = (api_key_env or entry.get("api_key_env")
                or _env_name_of(provider))
    if env_name:
        entry["api_key_env"] = env_name
    if entry:
        providers[provider] = entry
    else:
        providers.pop(provider, None)
    data["providers"] = providers
    path = save(data)
    if key and env_name:
        os.environ[env_name] = str(key).strip()
    return path


def set_api_key_alt(provider: str, key: str, api_key_alt_env: str = "") -> Path:
    """保存某提供方的**备用**密钥（主 Key 被拒/额度用尽时自动启用）。

    与主 Key 完全对称：同样的落盘位置、同样的环境变量同步、留空即删除。
    """
    provider = str(provider or "").strip()
    data = load()
    providers = dict(data["providers"])
    entry = dict(providers.get(provider) or {})
    if key:
        entry["api_key_alt"] = str(key).strip()
    else:
        entry.pop("api_key_alt", None)
    env_name = (api_key_alt_env or entry.get("api_key_alt_env")
                or _env_name_alt_of(provider))
    if env_name:
        entry["api_key_alt_env"] = env_name
    if not entry.get("api_key_env"):
        main_env = _env_name_of(provider)      # 顺手补齐主 Key 的变量名，文件自解释
        if main_env:
            entry["api_key_env"] = main_env
    if entry:
        providers[provider] = entry
    else:
        providers.pop(provider, None)
    data["providers"] = providers
    path = save(data)
    if key and env_name:
        os.environ[env_name] = str(key).strip()
    return path


def _env_name_of(provider: str) -> str:
    """从提供方注册表查密钥环境变量名（延迟导入避免循环依赖）"""
    try:
        from core.providers import get_provider

        return get_provider(provider).api_key_env or ""
    except Exception:
        return ""


def _env_name_alt_of(provider: str) -> str:
    """从提供方注册表查备用密钥环境变量名"""
    try:
        from core.providers import get_provider

        return get_provider(provider).api_key_alt_env or ""
    except Exception:
        return ""


def apply_to_environment() -> dict[str, str]:
    """把持久化的密钥同步进进程环境变量（已有同名环境变量时不覆盖）。

    已有的环境变量代表「本次运行显式指定」（--deepseek-key / 用户 shell 设置），
    优先级高于文件里保存的值——这与 core/providers.py 的层次一致：
    内置默认 < config/llm.json < 用户配置 < 环境变量。

    主 Key 与备用 Key 分别同步到各自的变量（DEEPSEEK_API_KEY /
    DEEPSEEK_API_KEY_BACKUP），互不影响。
    """
    applied: dict[str, str] = {}
    for provider, entry in load()["providers"].items():
        for key_field, env_field, lookup in (
                ("api_key", "api_key_env", _env_name_of),
                ("api_key_alt", "api_key_alt_env", _env_name_alt_of)):
            key = str(entry.get(key_field) or "")
            if not key:
                continue
            env_name = str(entry.get(env_field) or "") or lookup(provider)
            if not env_name or os.environ.get(env_name):
                continue
            os.environ[env_name] = key
            applied[env_name] = provider
    return applied


# ---------------------------------------------------------------- 展示 / CLI

def describe() -> str:
    """可读摘要（密钥只报是否设置，绝不回显）"""
    data = load()
    path = config_path()
    lines = [f"配置文件：{path}（{'存在' if path.is_file() else '尚未创建'}）",
             f"激活模型：{data.get('active_model') or '（未设置）'}"]
    providers = data.get("providers") or {}
    if not providers:
        lines.append("提供方密钥：无")
    for name, entry in providers.items():
        bits = []
        bits.append("密钥✓" if entry.get("api_key") else "密钥✗")
        if entry.get("api_key_alt"):
            bits.append("备用✓")
        if entry.get("api_key_env"):
            bits.append(f"env={entry['api_key_env']}")
        if entry.get("api_key_alt_env"):
            bits.append(f"alt_env={entry['api_key_alt_env']}")
        if entry.get("model"):
            bits.append(f"model={entry['model']}")
        lines.append(f"  - {name}: " + "  ".join(bits))
    if data.get("updated"):
        lines.append(f"最后保存：{data['updated']}")
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m core.user_config",
        description="查看/设置用户级配置（%USERPROFILE%\\.networkclaw\\networkclaw.json）")
    ap.add_argument("--path", action="store_true", help="只打印配置文件路径")
    ap.add_argument("--set-model", metavar="名称", help="写入激活模型（提供方名）")
    ap.add_argument("--set-key", nargs=2, metavar=("提供方", "密钥"),
                    help="保存某提供方的主密钥（同时写入环境变量）")
    ap.add_argument("--set-alt-key", nargs=2, metavar=("提供方", "密钥"),
                    help="保存某提供方的备用密钥（主 Key 被拒/额度用尽时自动启用）")
    ap.add_argument("--clear-key", metavar="提供方", help="删除某提供方保存的主密钥")
    ap.add_argument("--clear-alt-key", metavar="提供方", help="删除某提供方保存的备用密钥")
    args = ap.parse_args(argv)

    if args.path:
        print(config_path())
        return 0
    if args.set_model:
        print(f"已保存激活模型：{args.set_model} → {set_active_model(args.set_model)}")
        return 0
    if args.set_key:
        provider, key = args.set_key
        path = set_api_key(provider, key)
        print(f"已保存 {provider} 的主密钥（不回显）→ {path}")
        return 0
    if args.set_alt_key:
        provider, key = args.set_alt_key
        path = set_api_key_alt(provider, key)
        print(f"已保存 {provider} 的备用密钥（不回显）→ {path}")
        return 0
    if args.clear_key:
        path = set_api_key(args.clear_key, "")
        print(f"已清除 {args.clear_key} 的主密钥 → {path}")
        return 0
    if args.clear_alt_key:
        path = set_api_key_alt(args.clear_alt_key, "")
        print(f"已清除 {args.clear_alt_key} 的备用密钥 → {path}")
        return 0
    print(describe())
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
