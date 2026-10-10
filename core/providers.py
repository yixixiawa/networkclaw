"""模型提供方注册表：把「本地 llama-server」与云端 API（DeepSeek 等）统一成同一套抽象。

为什么需要：
    原来是单一模型写死在 core/llm_client.py 里（端点、模型名硬编码）。要支持
    DeepSeek 这类云端 API、并且后续让本地与云端**并行**跑，就必须先有一个
    统一的「提供方（Provider）」概念：调用方只说「用哪个提供方」，不关心
    端点怎么拼、要不要鉴权、支不支持图片。

能力标记（决定请求怎么组装、能不能接某类任务）：
    supports_vision         能否接收图片（本地 Qwen3.5-9B + mmproj 可以；
                            云端 DeepSeek V4.1 Flash 原生多模态，也可以）
    supports_tools          能否返回 tool_calls（Agent 模式依赖）
    supports_thinking       是否输出 reasoning_content（本地 Qwen / DeepSeek 思考模式）
    supports_sampling       是否接受 temperature 等采样参数
    supports_stream_options 是否接受 stream_options.include_usage

配置来源（后者覆盖前者）：
    1. 内置默认（本地指向 core/llama_start.py 的端口配置，云端指向 api.deepseek.com）
    2. 项目根 config/llm.json（可增删提供方、改模型名、填 api_key）
    3. 环境变量 / 项目根 .env（DEEPSEEK_API_KEY 等；推荐用环境变量而不是把密钥写进文件）

调用方式：
    from core.providers import get_provider
    p = get_provider()            # 取当前激活的提供方
    p = get_provider("deepseek-flash")  # 指定

命令行自检：
    python -m core.providers            # 列出所有提供方与配置状态（不联网）
    python -m core.providers --check    # 逐个探测可用性（本地探端口、云端验证 API Key）
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import requests

from core.net import ensure_localhost_bypass
from core.paths import BASE_DIR

# 导入即让本机回环绕过系统代理（本地提供方的调用依赖它）
ensure_localhost_bypass()

CONFIG_FILE = BASE_DIR / "config" / "llm.json"
ENV_FILE = BASE_DIR / ".env"

DEFAULT_PROVIDER = "local"
ENV_ACTIVE = ("NETWORKCLAW_PROVIDER", "NETWORKCLAW_DEFAULT_PROVIDER")

# 旧提供方名 → 现名（DeepSeek 2026-09 模型线换代：chat/reasoner → flash/pro）
ALIASES = {
    "deepseek": "deepseek-flash",
    "deepseek-chat": "deepseek-flash",
    "deepseek-v4-flash": "deepseek-flash",
    "deepseek-reasoner": "deepseek-pro",
    "deepseek-v4-pro": "deepseek-pro",
}


# ---------------------------------------------------------------- 环境变量

def load_env_file(path: Path | None = None, override: bool = False) -> dict[str, str]:
    """读取项目根 .env（KEY=VALUE 每行一条），默认不覆盖已有环境变量。

    只做最朴素的解析，够用即可：支持 # 注释、空行、值两侧引号。
    """
    path = path or ENV_FILE
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            loaded[key] = value
            if override or key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass
    return loaded


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return default


def save_env_file(updates: dict[str, str], path: Path | None = None) -> Path:
    """把若干 KEY=VALUE 写进 .env（GUI 的设置页保存密钥用）。

    保留原有注释与其它行，同名键就地更新，不存在的键追加到末尾；
    同时同步到当前进程环境变量，保存后立即生效、无需重启。
    """
    path = path or ENV_FILE
    lines: list[str] = []
    if path.is_file():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []

    remaining = {k: v for k, v in (updates or {}).items() if k}
    out: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(raw)
    for key, value in remaining.items():
        out.append(f"{key}={value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    for key, value in (updates or {}).items():
        if key:
            os.environ[key] = value
    return path


# ---------------------------------------------------------------- Provider

@dataclass(frozen=True)
class Provider:
    """一个可调用的模型端点（本地或云端）"""

    name: str                      # 内部标识：local / deepseek-flash / deepseek-pro
    label: str                     # 展示名
    kind: str = "cloud"            # local | cloud
    base_url: str = ""
    model: str = ""
    chat_path: str = "/chat/completions"
    api_key: str = ""              # 直填的密钥（不推荐，优先用环境变量）
    api_key_env: str = ""          # 密钥所在的环境变量名
    timeout: int = 600
    supports_vision: bool = False
    supports_tools: bool = True
    supports_thinking: bool = False
    supports_sampling: bool = True
    supports_stream_options: bool = True
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict = field(default_factory=dict)
    note: str = ""

    # ------------------------------------------------ 密钥
    @property
    def api_key_value(self) -> str:
        """环境变量优先于配置文件中直填的密钥"""
        if self.api_key_env:
            value = (os.environ.get(self.api_key_env) or "").strip()
            if value:
                return value
        return (self.api_key or "").strip()

    @property
    def is_configured(self) -> bool:
        """本地提供方无需密钥；云端必须能取到密钥"""
        return True if self.kind == "local" else bool(self.api_key_value)

    @property
    def needs_key(self) -> bool:
        return self.kind != "local"

    # ------------------------------------------------ 请求组装
    @property
    def chat_urls(self) -> list[str]:
        """候选请求地址。

        OpenAI 兼容服务的路径写法有两种（`/chat/completions` 与 `/v1/chat/completions`），
        统一按候选列表逐个试，命中后缓存，避免把用户卡在 404 上。
        """
        root = self.base_url.rstrip("/")
        urls = [root + self.chat_path]
        if not root.endswith("/v1"):
            urls.append(root + "/v1" + self.chat_path)
        # 去重保序
        seen, out = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    @property
    def models_url(self) -> str:
        """探测用：OpenAI 兼容的模型列表地址"""
        root = self.base_url.rstrip("/")
        return f"{root}/models"

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        key = self.api_key_value
        if key:
            h["Authorization"] = f"Bearer {key}"
        h.update(self.extra_headers or {})
        return h

    def describe_capabilities(self) -> str:
        caps = []
        caps.append("图片✓" if self.supports_vision else "图片✗")
        caps.append("工具✓" if self.supports_tools else "工具✗")
        caps.append("思考✓" if self.supports_thinking else "思考✗")
        return " ".join(caps)

    def status_line(self, active: bool = False) -> str:
        mark = "→" if active else " "
        auth = "无需密钥" if not self.needs_key else (
            f"密钥✓（{self.api_key_env or '配置文件'}）" if self.api_key_value
            else f"密钥✗（请设置 {self.api_key_env or 'DEEPSEEK_API_KEY'}）")
        return (f"{mark} {self.name:<18} {self.label:<24} {self.kind:<6} "
                f"{self.model:<20} {self.describe_capabilities()}  {auth}")

    def with_overrides(self, data: dict) -> "Provider":
        """用配置字典覆盖字段（只认已知字段，未知字段忽略，避免配置写错就崩）"""
        known = {f for f in self.__dataclass_fields__ if f != "name"}
        patch = {k: v for k, v in (data or {}).items() if k in known and v is not None}
        if "timeout" in patch:
            try:
                patch["timeout"] = int(patch["timeout"])
            except (TypeError, ValueError):
                patch.pop("timeout")
        for key in ("extra_headers", "extra_body"):
            if key in patch and not isinstance(patch[key], dict):
                patch.pop(key)
        return Provider(**{**{f: getattr(self, f) for f in self.__dataclass_fields__}, **patch})


# ---------------------------------------------------------------- 内置默认

def _builtin() -> dict[str, Provider]:
    # 本地提供方的端口与模型来自 core/llama_start.py（那里是唯一配置点）
    from core import llama_start as _ls

    local = Provider(
        name="local",
        label="本地 Qwen3.5-9B（llama-server）",
        kind="local",
        base_url=f"{_ls.BASE_URL}/v1",
        model="Qwen3.5-9B",
        timeout=600,
        supports_vision=True,     # 带 --mmproj 时具备识图能力
        supports_tools=True,      # 需 --jinja
        supports_thinking=True,
        note="离线可用；图像识别、设备操作均走它",
    )
    # DeepSeek 事实（2026-09-22 按官方文档 api-docs.deepseek.com 核实）：
    #   - deepseek-flash    = DeepSeek-V4.1-Flash：原生多模态（图片按 1024 token/张计费），
    #     1M 上下文 / 384K 输出，thinking/non-thinking 双模式，支持 Tool Calls
    #   - deepseek-v4-pro   = DeepSeek-V4-Pro：纯文本，同样支持思考模式与工具调用
    #   - 旧名 deepseek-chat / deepseek-reasoner / deepseek-v4-flash 已退役或即将下线，
    #     新代码统一用显式 V4 模型 ID；旧提供方名由 ALIASES 兼容
    deepseek_flash = Provider(
        name="deepseek-flash",
        label="DeepSeek V4.1 Flash（多模态）",
        kind="cloud",
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        api_key_env="DEEPSEEK_API_KEY",
        timeout=300,
        supports_vision=True,     # 原生多模态：可直接接收 image_url（data URI 已实测兼容）
        supports_tools=True,
        supports_thinking=True,   # 默认非思考模式；需要时在 config/llm.json 的 extra_body 里加 thinking
        supports_sampling=True,
        note="看图/拓扑识读可直接交给它；高并发（2500）、长上下文 1M/输出 384K",
    )
    deepseek_pro = Provider(
        name="deepseek-pro",
        label="DeepSeek V4 Pro（深度推理）",
        kind="cloud",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        api_key_env="DEEPSEEK_API_KEY",
        timeout=600,
        supports_vision=False,    # V4 Pro 为纯文本；图片由视觉桥接转文字后注入
        supports_tools=True,
        supports_thinking=True,
        supports_sampling=True,
        extra_body={"thinking": {"type": "enabled"}},  # 默认开思考；不接受时 400 会自动降级
        note="复杂推理/排障分析，输出 reasoning_content；不支持图片输入",
    )
    return {p.name: p for p in (local, deepseek_flash, deepseek_pro)}


# ---------------------------------------------------------------- 注册表

_providers: dict[str, Provider] | None = None
_active: str | None = None


def _apply_env_overrides(table: dict[str, Provider]) -> dict[str, Provider]:
    """环境变量覆盖（最后一层，优先级最高）"""
    out = dict(table)
    if "deepseek-flash" in out:
        base = out["deepseek-flash"]
        out["deepseek-flash"] = base.with_overrides({
            "base_url": _env("DEEPSEEK_BASE_URL", default=base.base_url),
            "model": _env("DEEPSEEK_MODEL", default=base.model),
            "api_key": _env("DEEPSEEK_API_KEY", default=base.api_key),
        })
    if "deepseek-pro" in out:
        base = out["deepseek-pro"]
        out["deepseek-pro"] = base.with_overrides({
            "base_url": _env("DEEPSEEK_BASE_URL", default=base.base_url),
            "model": _env("DEEPSEEK_PRO_MODEL", default=base.model),
            "api_key": _env("DEEPSEEK_API_KEY", default=base.api_key),
        })
    if "local" in out:
        # 允许用环境变量指向别处启动的 llama-server（例如另一台机器的端口转发）
        base = out["local"]
        out["local"] = base.with_overrides({
            "base_url": _env("NETWORKCLAW_LOCAL_BASE_URL", default=base.base_url),
            "model": _env("NETWORKCLAW_LOCAL_MODEL", default=base.model),
        })
    return out


def load_providers(refresh: bool = False) -> dict[str, Provider]:
    """加载提供方注册表（内置默认 → config/llm.json → 环境变量 / .env）"""
    global _providers
    if _providers is not None and not refresh:
        return _providers

    load_env_file()
    table = _builtin()

    if CONFIG_FILE.is_file():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[提供方配置] config/llm.json 读取失败，使用内置默认：{type(e).__name__}: {e}")
            data = {}
        for name, conf in (data.get("providers") or {}).items():
            if not isinstance(conf, dict):
                continue
            if name in table:
                table[name] = table[name].with_overrides(conf)
            else:
                # 新增自定义提供方：必须有 base_url 与 model
                if conf.get("base_url") and conf.get("model"):
                    table[name] = Provider(
                        name=name,
                        label=conf.get("label", name),
                        kind=conf.get("kind", "cloud"),
                        base_url=conf["base_url"],
                        model=conf["model"],
                        chat_path=conf.get("chat_path", "/chat/completions"),
                        api_key=conf.get("api_key", ""),
                        api_key_env=conf.get("api_key_env", ""),
                        timeout=int(conf.get("timeout", 600)),
                        supports_vision=bool(conf.get("supports_vision", False)),
                        supports_tools=bool(conf.get("supports_tools", True)),
                        supports_thinking=bool(conf.get("supports_thinking", False)),
                        supports_sampling=bool(conf.get("supports_sampling", True)),
                        supports_stream_options=bool(conf.get("supports_stream_options", True)),
                        extra_headers=conf.get("extra_headers") or {},
                        extra_body=conf.get("extra_body") or {},
                        note=conf.get("note", ""),
                    )
                else:
                    print(f"[提供方配置] 忽略不完整的提供方「{name}」：需要 base_url 与 model")
        default_name = data.get("default")
    else:
        default_name = None

    table = _apply_env_overrides(table)
    _providers = table

    global _active
    env_active = _env(*ENV_ACTIVE)
    _active = env_active if env_active in table else (
        default_name if default_name in table else
        (_active if _active in table else DEFAULT_PROVIDER))
    if _active not in table:
        _active = next(iter(table))
    return _providers


def list_providers(refresh: bool = False) -> list[Provider]:
    """按注册顺序返回所有提供方"""
    return list(load_providers(refresh).values())


def get_provider(name: str | None = None, refresh: bool = False) -> Provider:
    """取提供方；name 为空取当前激活的。名称不存在时抛 KeyError（附可选值）"""
    table = load_providers(refresh)
    if name in (None, "", "auto", "default"):
        return table[active_name()]
    key = str(name).strip()
    if key in table:
        return table[key]
    lower = {k.lower(): k for k in table}
    if key.lower() in lower:
        return table[lower[key.lower()]]
    if key.lower() in ALIASES:  # 旧名兼容：deepseek → deepseek-flash 等
        return table[ALIASES[key.lower()]]
    raise KeyError(f"未知的模型提供方「{name}」，可选：{', '.join(table)}")


def active_name() -> str:
    load_providers()
    return _active or DEFAULT_PROVIDER


def set_active(name: str, refresh: bool = False) -> Provider:
    """切换当前激活的提供方（仅本次运行有效，不写回配置文件）"""
    global _active
    provider = get_provider(name, refresh)  # 名称非法时直接抛错
    _active = provider.name
    return provider


def get_active() -> Provider:
    return get_provider(None)


def configured_providers(refresh: bool = False) -> list[Provider]:
    """已可用的提供方（本地恒可用；云端需有密钥）"""
    return [p for p in list_providers(refresh) if p.is_configured]


def vision_capable(refresh: bool = False) -> Provider | None:
    """找一个能看图的提供方（用于多模态桥接：文本模型 + 本地视觉模型协作）"""
    providers = list_providers(refresh)
    active = get_active()
    if active.supports_vision:
        return active
    for p in providers:
        if p.supports_vision and p.kind == "local":
            return p
    return next((p for p in providers if p.supports_vision), None)


# ---------------------------------------------------------------- 探测

def probe(provider: Provider, timeout: float = 8.0) -> dict:
    """探测提供方是否可用：本地探端口，云端用 /models 校验密钥。"""
    result = {"name": provider.name, "ok": False, "status": None, "detail": "", "latency": None}
    if provider.needs_key and not provider.api_key_value:
        result["detail"] = (f"未配置 API Key。请设置环境变量 {provider.api_key_env or 'DEEPSEEK_API_KEY'}，"
                            f"或写入 config/llm.json")
        return result

    import time
    start = time.time()
    try:
        resp = requests.get(provider.models_url, headers=provider.headers(), timeout=timeout)
    except requests.RequestException as e:
        result["detail"] = f"连接失败：{type(e).__name__}: {e}"
        return result

    result["status"] = resp.status_code
    result["latency"] = round(time.time() - start, 2)
    if resp.status_code == 200:
        result["ok"] = True
        names: list[str] = []
        try:
            names = [m.get("id") for m in (resp.json().get("data") or []) if m.get("id")]
        except Exception:
            pass
        if not names or provider.model in names:
            result["detail"] = "服务可用"
        else:
            result["detail"] = (f"服务可用，但模型列表中未出现 {provider.model}"
                                f"（共 {len(names)} 个模型：{', '.join(names[:6])}…）")
    elif resp.status_code in (401, 403):
        result["detail"] = f"鉴权失败（HTTP {resp.status_code}），请检查 API Key 是否正确或已过期"
    else:
        result["detail"] = f"HTTP {resp.status_code}：{(resp.text or '')[:160]}"
    return result


def check_all(verbose: bool = True) -> dict[str, dict]:
    """逐个探测并打印结果，返回 {name: probe结果}"""
    out: dict[str, dict] = {}
    for p in list_providers():
        if not p.is_configured:
            out[p.name] = {"name": p.name, "ok": False, "detail":
                           f"未配置密钥（{p.api_key_env or 'DEEPSEEK_API_KEY'}）"}
        else:
            out[p.name] = probe(p)
        if verbose:
            r = out[p.name]
            flag = "可用" if r["ok"] else "不可用"
            extra = f"（{r['latency']}s）" if r.get("latency") else ""
            print(f"[{flag}] {p.name:<18} {p.model:<20} {extra} {r['detail']}")
    return out


def describe_table(active: str | None = None) -> str:
    """格式化输出提供方总表（给 CLI 与启动界面用）"""
    active = active or active_name()
    lines = ["可用模型提供方：", f"  {'名称':<18} {'说明':<24} {'类型':<6} {'模型':<20} 能力与密钥",
             "  " + "-" * 96]
    for p in list_providers():
        lines.append(p.status_line(active=(p.name == active)))
    return "\n".join(lines)


if __name__ == "__main__":
    import sys as _sys

    load_providers(refresh=True)
    if "--check" in _sys.argv:
        print(describe_table())
        print("\n开始探测可用性…")
        check_all(verbose=True)
    else:
        print(describe_table())
        print(f"\n当前激活：{active_name()}")
        print("提示：加 --check 可探测可用性（本地探端口、云端验证密钥）")
