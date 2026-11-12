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

备用与降级：
    · 每个提供方可配「主 Key + 备用 Key」两个额度（`api_key_env` / `api_key_alt_env`），
      主 Key 被拒（401/402/429）时自动换备用 Key 重试，模型与端点不变；
    · 每个提供方可配 `fallback` 降级链（提供方名元组），主提供方连不上/额度用尽时
      按顺序自动切到备用提供方（智谱 GLM、Kimi 就是内置的两级备用）；
    · 只有「一个字都还没吐给用户」时才切换，避免流到一半换模型导致回答拼接错乱。

配置来源（后者覆盖前者）：
    1. 内置默认（本地指向 core/llama_start.py 的端口配置，云端指向各厂商网关）
    2. 项目根 config/llm.json（可增删提供方、改模型名、填 api_key、改 fallback）
    3. 用户级配置 %USERPROFILE%\\.networkclaw\\networkclaw.json（GUI/CLI 保存的
       激活模型与密钥；由 core.user_config 管理，见该模块 docstring）
    4. 环境变量 / 项目根 .env（DEEPSEEK_API_KEY / ZHIPU_API_KEY / MOONSHOT_API_KEY
       以及各自的 *_BACKUP；本次运行显式指定，优先级最高）

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

#: 关掉自动降级的开关（排障时用：只想看主提供方真实报错，不希望被备用接管）
ENV_NO_FALLBACK = "NETWORKCLAW_NO_FALLBACK"

# 旧提供方名 → 现名（DeepSeek 2026-09 模型线换代：chat/reasoner → flash/pro）
ALIASES = {
    "deepseek": "deepseek-flash",
    "deepseek-chat": "deepseek-flash",
    "deepseek-v4-flash": "deepseek-flash",
    "deepseek-reasoner": "deepseek-pro",
    "deepseek-v4-pro": "deepseek-pro",
    # 备用提供方的口语名（用户在设置/CLI 里多半这么写）
    "glm": "glm-4.6",
    "zhipu": "glm-4.6",
    "chatglm": "glm-4.6",
    "kimi": "kimi-k2.5",
    "moonshot": "kimi-k2.5",
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

    name: str                      # 内部标识：local / deepseek-flash / glm-4.6 …
    label: str                     # 展示名
    kind: str = "cloud"            # local | cloud
    base_url: str = ""
    model: str = ""
    chat_path: str = "/chat/completions"
    api_key: str = ""              # 直填的主密钥（不推荐，优先用环境变量）
    api_key_env: str = ""          # 主密钥所在的环境变量名
    api_key_alt: str = ""          # 直填的备用密钥
    api_key_alt_env: str = ""      # 备用密钥所在的环境变量名（主 Key 被拒时用它）
    fallback: tuple[str, ...] = ()  # 主提供方不可用时依次尝试的备用提供方名
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
    def api_key_alt_value(self) -> str:
        """备用密钥（没有就返回空串）"""
        if self.api_key_alt_env:
            value = (os.environ.get(self.api_key_alt_env) or "").strip()
            if value:
                return value
        return (self.api_key_alt or "").strip()

    def key_candidates(self) -> list[tuple[str, str]]:
        """可用密钥列表 [(槽位, 密钥)]：主 Key 在前、备用 Key 在后，重复的只留一次。

        槽位只用于日志与提示（「主」「备用」），不含密钥本身——密钥不落日志。
        """
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for slot, key in (("主", self.api_key_value), ("备用", self.api_key_alt_value)):
            if key and key not in seen:
                seen.add(key)
                out.append((slot, key))
        return out

    @property
    def is_configured(self) -> bool:
        """本地提供方无需密钥；云端至少要有一个 Key（主或备用）"""
        return True if self.kind == "local" else bool(self.key_candidates())

    @property
    def needs_key(self) -> bool:
        return self.kind != "local"

    @property
    def key_hint(self) -> str:
        """缺 Key 时给用户看的变量名（主 + 备用）"""
        names = [n for n in (self.api_key_env, self.api_key_alt_env) if n]
        return " 或 ".join(names) or "DEEPSEEK_API_KEY"

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
        if not self.needs_key:
            auth = "无需密钥"
        elif self.api_key_value:
            auth = f"密钥✓（{self.api_key_env or '配置文件'}）"
            if self.api_key_alt_value:
                auth += "＋备用✓"
        elif self.api_key_alt_value:
            auth = f"备用密钥✓（{self.api_key_alt_env or '配置文件'}，主 Key 缺失）"
        else:
            auth = f"密钥✗（请设置 {self.key_hint}）"
        if self.fallback:
            auth += f" ⇢{'/'.join(self.fallback)}"
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
        if "fallback" in patch:
            # JSON 里写不了元组：允许 ["a","b"] 或 "a,b"，统一收敛成元组
            raw = patch["fallback"]
            if isinstance(raw, str):
                patch["fallback"] = tuple(x.strip() for x in raw.split(",") if x.strip())
            elif isinstance(raw, (list, tuple)):
                patch["fallback"] = tuple(str(x).strip() for x in raw if str(x).strip())
            else:
                patch.pop("fallback")
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
        # 本地服务没起来（忘记启动 / 端口被占）时，有云 Key 就自动接管，
        # 否则用户只看到「连接失败」，会以为整个系统坏了。没有 Key 的会被跳过。
        fallback=("deepseek-flash", "glm-4.6", "kimi-k2.5"),
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
        api_key_alt_env="DEEPSEEK_API_KEY_BACKUP",
        timeout=300,
        supports_vision=True,     # 原生多模态：可直接接收 image_url（data URI 已实测兼容）
        supports_tools=True,
        supports_thinking=True,   # 默认非思考模式；需要时在 config/llm.json 的 extra_body 里加 thinking
        supports_sampling=True,
        fallback=("glm-4.6", "kimi-k2.5"),
        note="看图/拓扑识读可直接交给它；高并发（2500）、长上下文 1M/输出 384K",
    )
    deepseek_pro = Provider(
        name="deepseek-pro",
        label="DeepSeek V4 Pro（深度推理）",
        kind="cloud",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        api_key_env="DEEPSEEK_API_KEY",
        api_key_alt_env="DEEPSEEK_API_KEY_BACKUP",
        timeout=600,
        supports_vision=False,    # V4 Pro 为纯文本；图片由视觉桥接转文字后注入
        supports_tools=True,
        supports_thinking=True,
        supports_sampling=True,
        extra_body={"thinking": {"type": "enabled"}},  # 默认开思考；不接受时 400 会自动降级
        fallback=("deepseek-flash", "glm-4.6", "kimi-k2.5"),
        note="复杂推理/排障分析，输出 reasoning_content；不支持图片输入",
    )
    # ---- 备用提供方（2026-11 接入，端点与模型按各厂商官方文档核实）----
    # 智谱：https://open.bigmodel.cn/api/paas/v4 + glm-4.6（OpenAI 兼容，
    #       thinking 用 {"type":"enabled"} 开启，返回 reasoning_content）
    glm = Provider(
        name="glm-4.6",
        label="智谱 GLM-4.6（备用）",
        kind="cloud",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4.6",
        api_key_env="ZHIPU_API_KEY",
        api_key_alt_env="ZHIPU_API_KEY_BACKUP",
        timeout=300,
        supports_vision=False,    # GLM-4.6 为文本模型；看图请走 glm-4.5v 或视觉桥接
        supports_tools=True,
        supports_thinking=True,
        supports_sampling=True,
        extra_body={"thinking": {"type": "enabled"}},  # 不接受时 400 自动降级（连 extra_body 一起丢）
        fallback=("kimi-k2.5", "deepseek-flash"),
        note="备用一号：DeepSeek 额度用尽/鉴权失败时接手，中文与工具调用稳定",
    )
    # Kimi：https://api.moonshot.cn/v1 + kimi-k2.5（OpenAI 兼容，支持图片输入与
    #       思考/非思考模式，原生 function calling）
    kimi = Provider(
        name="kimi-k2.5",
        label="Kimi K2.5（备用）",
        kind="cloud",
        base_url="https://api.moonshot.cn/v1",
        model="kimi-k2.5",
        api_key_env="MOONSHOT_API_KEY",
        api_key_alt_env="MOONSHOT_API_KEY_BACKUP",
        timeout=300,
        supports_vision=True,     # K2.5 支持视觉与文本输入
        supports_tools=True,
        supports_thinking=True,   # 返回 reasoning_content 时照常展示
        supports_sampling=True,
        fallback=("glm-4.6", "deepseek-flash"),
        note="备用二号：长上下文 + 图片输入，适合接在 GLM 之后再兜一层",
    )
    return {p.name: p for p in (local, deepseek_flash, deepseek_pro, glm, kimi)}


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
            "api_key_alt": _env("DEEPSEEK_API_KEY_BACKUP", default=base.api_key_alt),
        })
    if "deepseek-pro" in out:
        base = out["deepseek-pro"]
        out["deepseek-pro"] = base.with_overrides({
            "base_url": _env("DEEPSEEK_BASE_URL", default=base.base_url),
            "model": _env("DEEPSEEK_PRO_MODEL", default=base.model),
            "api_key": _env("DEEPSEEK_API_KEY", default=base.api_key),
            "api_key_alt": _env("DEEPSEEK_API_KEY_BACKUP", default=base.api_key_alt),
        })
    if "local" in out:
        # 允许用环境变量指向别处启动的 llama-server（例如另一台机器的端口转发）
        base = out["local"]
        out["local"] = base.with_overrides({
            "base_url": _env("NETWORKCLAW_LOCAL_BASE_URL", default=base.base_url),
            "model": _env("NETWORKCLAW_LOCAL_MODEL", default=base.model),
        })
    if "glm-4.6" in out:
        # 智谱：换中转网关、换模型（如 glm-4.5v）都走这几个变量
        base = out["glm-4.6"]
        out["glm-4.6"] = base.with_overrides({
            "base_url": _env("ZHIPU_BASE_URL", "GLM_BASE_URL", default=base.base_url),
            "model": _env("ZHIPU_MODEL", "GLM_MODEL", default=base.model),
            "api_key": _env("ZHIPU_API_KEY", "GLM_API_KEY", default=base.api_key),
            "api_key_alt": _env("ZHIPU_API_KEY_BACKUP", "GLM_API_KEY_BACKUP",
                                default=base.api_key_alt),
        })
    if "kimi-k2.5" in out:
        base = out["kimi-k2.5"]
        out["kimi-k2.5"] = base.with_overrides({
            "base_url": _env("MOONSHOT_BASE_URL", "KIMI_BASE_URL", default=base.base_url),
            "model": _env("MOONSHOT_MODEL", "KIMI_MODEL", default=base.model),
            "api_key": _env("MOONSHOT_API_KEY", "KIMI_API_KEY", default=base.api_key),
            "api_key_alt": _env("MOONSHOT_API_KEY_BACKUP", "KIMI_API_KEY_BACKUP",
                                default=base.api_key_alt),
        })
    return out


def fallback_enabled() -> bool:
    """是否允许自动降级（`NETWORKCLAW_NO_FALLBACK=1` 可临时关掉，便于看主提供方的原始报错）"""
    return (_env(ENV_NO_FALLBACK) or "").strip().lower() not in ("1", "true", "yes", "on")


def fallback_chain(provider: Provider | str, refresh: bool = False) -> list[Provider]:
    """按 fallback 声明算出「真正可用」的备用提供方序列。

    三条硬规则：
        1. 只留当前就绪的（云端要有主 Key 或备用 Key），没配 Key 的不进队列，
           免得把用户拖进一连串必然失败的 HTTP 401；
        2. 去环：A→B→A 这种互指只走一遍（`local → deepseek → glm → kimi` 走完即止）；
        3. 自己不出现在自己的降级链里。

    返回顺序即尝试顺序；取不到就返回空列表（调用方按原错误抛给用户）。
    """
    if not fallback_enabled():
        return []
    try:
        start = provider if isinstance(provider, Provider) else get_provider(provider, refresh)
    except KeyError:
        return []

    out: list[Provider] = []
    seen = {start.name}
    queue = [n for n in (start.fallback or ())]
    while queue:
        name = queue.pop(0)
        try:
            cand = get_provider(name, refresh)
        except KeyError:
            continue
        if cand.name in seen:
            continue
        seen.add(cand.name)
        if not cand.is_configured:
            continue        # 没配 Key 的备用直接跳过（不代表它不能是别人的备用）
        out.append(cand)
        queue.extend(c for c in (cand.fallback or ()) if c not in seen)
    return out


def _apply_user_overrides(table: dict[str, Provider]) -> tuple[dict[str, Provider], str]:
    """用户级配置覆盖（%USERPROFILE%\\.networkclaw\\networkclaw.json）。

    只覆盖「这台机器的这个用户」真正会改的东西：密钥、模型名、激活项。
    优先级介于 config/llm.json 与环境变量之间——环境变量代表本次运行显式
    指定（--deepseek-key / shell 里 export），仍然最高。

    返回 (新表, 用户配置里的激活提供方名)。配置读不出来时原样返回，
    绝不能因为用户配置文件缺失/损坏就让提供方加载失败。
    """
    try:
        from core import user_config

        data = user_config.load()
        user_config.apply_to_environment()   # 密钥同步进 env（已有 env 不覆盖）
    except Exception as e:  # noqa: BLE001  用户配置是增强项
        print(f"[用户配置] 读取失败，按默认继续：{type(e).__name__}: {e}")
        return table, ""

    out = dict(table)
    for name, entry in (data.get("providers") or {}).items():
        if name not in out or not isinstance(entry, dict):
            continue
        patch = {}
        if entry.get("api_key"):
            patch["api_key"] = entry["api_key"]
        if entry.get("api_key_alt"):
            patch["api_key_alt"] = entry["api_key_alt"]
        if entry.get("model"):
            patch["model"] = entry["model"]
        if patch:
            out[name] = out[name].with_overrides(patch)
    return out, str(data.get("active_model") or "")


def load_providers(refresh: bool = False) -> dict[str, Provider]:
    """加载提供方注册表（内置默认 → config/llm.json → 用户配置 → 环境变量 / .env）"""
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

    table, user_active = _apply_user_overrides(table)
    table = _apply_env_overrides(table)
    _providers = table

    global _active
    env_active = _env(*ENV_ACTIVE)
    _active = env_active if env_active in table else (
        user_active if user_active in table else
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

def _model_listed(model: str, names: list[str]) -> bool:
    """模型名是否出现在 /models 列表里（容忍 llama-server 的文件名式 id）。

    llama-server 的 /v1/models 返回 id 是 **gguf 文件名/路径**
    （如 "Qwen3.5-9B-Q4_K_M.gguf"），与配置里的模型名 "Qwen3.5-9B" 不完全相等。
    此前只做精确匹配，导致本地明明可用却提示
    「模型列表中未出现 Qwen3.5-9B」，徒增排查困扰。这里放宽为：
    精确匹配 / 互相包含 / 去扩展名后互相包含（均忽略大小写）。
    """
    m = model.lower().strip()
    for name in names:
        n = str(name).lower().strip()
        if not n:
            continue
        if m == n or m in n or n in m:
            return True
        # 去掉 gguf 扩展名与路径后再比一次（Qwen3.5-9B-Q4_K_M ↔ Qwen3.5-9B）
        stem = n.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        for ext in (".gguf",):
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
        if m and (m in stem or stem in m):
            return True
    return False


def probe(provider: Provider, timeout: float = 8.0) -> dict:
    """探测提供方是否可用：本地探端口，云端用 /models 校验密钥。"""
    result = {"name": provider.name, "ok": False, "status": None, "detail": "", "latency": None}
    if provider.needs_key and not provider.api_key_value and not provider.api_key_alt_value:
        result["detail"] = (f"未配置 API Key。请设置环境变量 {provider.key_hint}，"
                            f"或写入 config/llm.json / 用户配置")
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
        if not names or _model_listed(provider.model, names):
            result["detail"] = "服务可用"
        else:
            result["detail"] = (f"服务可用，但模型列表中未出现 {provider.model}"
                                f"（共 {len(names)} 个模型：{', '.join(names[:6])}…）")
    elif resp.status_code in (401, 403):
        result["detail"] = f"鉴权失败（HTTP {resp.status_code}），请检查 API Key 是否正确或已过期"
    elif resp.status_code == 404:
        # 有的 OpenAI 兼容网关（如智谱 v4）不提供 GET /models：端点本身没问题，
        # 只是没法定量校验，别误判成「提供方坏了」。
        result["detail"] = ("该网关未提供 /models 列表（HTTP 404），无法用本方式校验；"
                            "可发一次对话确认")
    else:
        result["detail"] = f"HTTP {resp.status_code}：{(resp.text or '')[:160]}"
    return result


def check_all(verbose: bool = True) -> dict[str, dict]:
    """逐个探测并打印结果，返回 {name: probe结果}"""
    out: dict[str, dict] = {}
    for p in list_providers():
        if not p.is_configured:
            out[p.name] = {"name": p.name, "ok": False, "detail":
                           f"未配置密钥（{p.key_hint}）"}
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
