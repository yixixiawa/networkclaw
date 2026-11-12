"""设备手册与命令历史：**运行期由本地模型自建自维护**的资产（不是代码里的固定内容）。

设计原则（按用户要求）：
    · 内容不写死在仓库里——手理由本地模型在首次接触设备时自己建档、配置成功后自己沉淀；
    · 文件只落本机工作目录（源码模式=项目根，打包模式=exe 旁边），`session/` 已进 .gitignore；
    · 本模块只做「文件读写 + 结构规范」，不做任何内容生成——内容由模型（经 MCP 工具）提供。

**一个对话一套技能**（用户明确要求，2026-10 起）：
    早期版本把所有对话的手册统一放在 `skills/<设备名>/SKILL.md`，导致对话 A 的踩坑
    记录会在对话 B 被检索出来，模型把别人的结论当成自己的经验。现在改为按会话隔离，
    布局由用户指定（路径解析在 core/session_skills.py）：

        session/<会话标识>/skill/<设备名>/SKILL.md          手册
        session/<会话标识>/skill/<设备名>/history.jsonl     命令历史（工具层自动追加）

    「当前会话」由 session_skills.current() 决定；本模块所有路径函数都走它，
    因此 MCP 服务端（独立子进程）与主程序看到的永远是同一个会话。
    旧版全局目录 `skills/` 与 `data/device_history/` 在本项目已清理（内容迁入
    `session/legacy-global/`）；`migrate_legacy()` 保留给仍持有旧副本的场景，
    源目录不存在时优雅跳过，运行期不读取。

安全约束：
    · 设备名与会话标识都做白名单过滤（禁路径分隔符 / 相对路径），杜绝越权写文件；
    · 手册与历史都有体积上限，避免模型反复追加把文件写爆。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from core import session_skills as ss
from core.file_lock import file_lock
from core.paths import BASE_DIR

# 旧版全局目录（仅迁移用，运行期不再读取）
SKILLS_DIR = BASE_DIR / "skills"
HISTORY_DIR = BASE_DIR / "data" / "device_history"

MANUAL_MAX_BYTES = 256 * 1024     # 单份手册上限
HISTORY_MAX_BYTES = 4 * 1024 * 1024
RESULT_MAX_CHARS = 4000           # 单条历史里回显截断长度

SECTIONS = ("设备信息", "拓扑关系", "常用配置", "注意事项")
_FILE_LOCK = threading.Lock()

#: Wiki 生成时让模型输出的两个一级小节（生成后逐节 replace 进手册）
WIKI_TOPICS = ("拓扑关系", "配置基线")

WIKI_SYSTEM_PROMPT = """你是网络设备文档工程师。给你一台设备的名称、当前配置回显和实测拓扑信息，
你要生成一份**简洁、可直接当背景知识用**的 Markdown 说明手册。

硬性要求：
1. 只输出两个一级小节，顺序与标题固定：
# 拓扑关系
# 配置基线
2. 「拓扑关系」写：上下游邻居（上级/下级、互联接口）、本设备角色、承载的 VLAN/网段；
   拓扑信息缺失的部分明确写「待确认」，禁止编造接口号、IP 或邻居。
3. 「配置基线」写：从当前配置里提炼的关键事实（VLAN 划分、接口模式 access/trunk/hybrid、
   管理地址、路由/链路聚合要点），用短 bullet；不要整段照抄配置原文，单条不超过 2 行。
4. 总长度不超过 60 行；不输出任何解释性文字、代码围栏之外的闲聊或开场白。"""


class ManualError(ValueError):
    """设备名非法 / 内容超限等可读错误"""


def safe_name(name: str) -> str:
    """校验设备名（既当文件名也当目录名），非法直接报错（错误类型保持 ManualError）"""
    try:
        return ss.safe_name(name, "设备名")
    except ss.SessionError as e:
        raise ManualError(str(e)) from None


def manual_path(name: str, session: str = "") -> Path:
    """手册路径：默认当前会话；显式传 session 可跨会话只读（用于「看看上次那个对话」）"""
    try:
        return ss.manual_path(name, session or None)
    except ss.SessionError as e:
        # 统一对外交 ManualError：调用方（MCP 工具层）按它捕获并转成可读文案
        raise ManualError(str(e)) from None


def history_path(name: str, session: str = "") -> Path:
    """命令历史路径：与手册同目录，一个设备一个文件"""
    try:
        return ss.history_path(name, session or None)
    except ss.SessionError as e:
        raise ManualError(str(e)) from None


# ---------------------------------------------------------------- 骨架

def skeleton(name: str, vendor: str = "", model: str = "", address: str = "",
             login: str = "", role: str = "", note: str = "") -> str:
    """手册骨架：结构固定、内容留空，由模型填写（信息来自用户 / 探测 / 拓扑快照）。

    冷启动优化：若型号命中 knowledge/device_profiles.py 的基线画像，就把该型号的
    通用要点（端口编号规则、默认行为、易错点）预填进「注意事项」。这样第 7 台
    从没见过的设备第一次建档时手册就不是空的——模型开局就知道"这个型号的口是
    0 基还是 1 基"，而不是等踩坑后再补。
    """
    desc_bits = [b for b in (vendor, model) if b]
    desc = " ".join(desc_bits) or "网络设备"
    addr = address or "（待确认）"

    baseline = ""
    try:
        from knowledge.device_profiles import baseline_tips
        baseline = baseline_tips(model)
    except Exception:
        baseline = ""       # 画像不可用不能阻断建档

    tips_body = baseline or "（执行过程中发现的坑：接口需先 shutdown、两端需同配等）"
    return f"""---
name: {name}
description: {desc}（{addr}）。当用户提到 {name} 或地址 {addr} 时使用。
generated: runtime        # 由本地模型在运行期自建，非仓库固定资产
updated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
---

# {name} 设备信息

- 厂商：{vendor or "（待确认）"}
- 型号：{model or "（待确认）"}
- 管理地址：{addr}
- 登录方式：{login or "（待确认，密码不写入本文件）"}
- 角色：{role or "（待确认）"}
{f"- 备注：{note}" if note else ""}

# 拓扑关系

（建档后由 PLAN/Wiki 生成流程自动补全：上下游邻居、互联接口、本设备角色）

# 常用配置

（配置验证有效后，由模型把命令序列与适用场景写在这里）

# 注意事项

{tips_body}
"""


# ---------------------------------------------------------------- 读写

def read_manual(name: str, session: str = "") -> str:
    p = manual_path(name, session)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def save_manual(name: str, content: str, session: str = "") -> int:
    """整篇写入（模型完全重写时用），返回字节数"""
    if not (content or "").strip():
        raise ManualError("手册内容不能为空")
    data = content.encode("utf-8")
    if len(data) > MANUAL_MAX_BYTES:
        raise ManualError(f"手册过大（{len(data)} 字节 > {MANUAL_MAX_BYTES}），请精简后重写")
    p = manual_path(name, session)
    p.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(p), _FILE_LOCK:
        tmp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=p.parent,
                    prefix=f".{p.name}.", suffix=".tmp", delete=False) as tmp:
                tmp.write(content)
                tmp_name = tmp.name
            os.replace(tmp_name, p)
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass
    return len(data)


def ensure_manual(name: str, session: str = "", **meta) -> tuple[str, bool]:
    """手册不存在则用骨架建档。返回 (手册内容, 是否新建)"""
    text = read_manual(name, session)
    if text:
        return text, False
    text = skeleton(name, **meta)
    save_manual(name, text, session)
    return text, True


def update_section(name: str, section: str, text: str,
                   mode: str = "append", title: str = "", session: str = "") -> str:
    """把内容写入指定小节（小节不存在就创建），返回处理后的整篇手册。

    Args:
        section: 目标小节名，通常是 设备信息 / 常用配置 / 注意事项
        text: 要写入的内容（命令序列、注意事项等）
        mode: append（追加，默认）或 replace（替换该小节全部内容）
        title: 追加时可选的小标题，插入为 `## <title>`
        session: 显式指定会话（默认当前会话；跨会话写入没有意义，仅测试用）
    """
    section = (section or "").strip() or "常用配置"
    if "\n#" in section or len(section) > 30:
        raise ManualError("小节名不合法（应为 30 字以内的短语，不含换行）")
    text = (text or "").strip()
    if not text:
        raise ManualError("要写入的内容不能为空")

    current = read_manual(name, session) or skeleton(name)
    stamp = datetime.now().strftime("%Y-%m-%d")
    block = f"## {title.strip()}（{stamp}）\n\n{text}\n" if title.strip() else f"{text}\n"

    lines = current.splitlines()
    head = f"# {section}"

    def _is_section(line: str) -> bool:
        """一级标题匹配：精确匹配，或标题以小节名结尾（骨架里写作「# <设备名> 设备信息」）"""
        if not line.startswith("# "):
            return False
        title = line[2:].strip()
        return title == section or title.endswith(section)

    start = next((i for i, ln in enumerate(lines) if _is_section(ln)), None)
    if start is None:                       # 小节不存在 → 追加到文末
        new_text = current.rstrip() + f"\n\n{head}\n\n{block}"
    else:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].startswith("# "):   # 下一个一级标题
                end = j
                break
        body = "\n".join(lines[start + 1:end])
        if mode == "replace":
            new_body = f"\n\n{block}\n"
        else:
            new_body = body.rstrip() + f"\n\n{block}\n"
        new_text = "\n".join(lines[:start + 1]) + new_body + "\n".join(lines[end:])
    save_manual(name, new_text.strip() + "\n", session)
    return read_manual(name, session)


# ---------------------------------------------------------------- Wiki 生成

def fetch_current_config(host: str, port: int = 0, username: str = "",
                         password: str = "", enable_password: str = "",
                         timeout: float = 30.0) -> str:
    """抓取设备当前配置（只读 display current-configuration）。

    供「新设备建档 → Wiki 化」流水线使用：独立于 MCP 工具层直接建会话，
    只下发 allow 级只读命令，不走确认流。失败抛异常（调用方决定如何降级）。
    """
    from core import device_conn

    sess = device_conn.open_telnet(
        host, port=int(port or 23), username=username, password=password,
        enable_password=enable_password, timeout=timeout)
    try:
        return sess.exec_command("display current-configuration",
                                 timeout=timeout) or ""
    finally:
        sess.close()


def topology_for_device(name: str, max_chars: int = 1500) -> str:
    """从实测拓扑快照里抠出与本设备相关的邻居/层级信息（供 Wiki 生成用）。"""
    try:
        from core import topology_flood
    except Exception:
        return ""
    try:
        topo = topology_flood.load_snapshot()
    except Exception:
        return ""
    if topo is None or not topo.devices:
        return ""
    target = name.lower()
    links = [lk for lk in topo.links
             if target in (lk.a_device.lower(), lk.b_device.lower())]
    if not links:
        return ""
    parent = topo.parents.get(name) or topo.parents.get(target) or ""
    lines = [f"- 实测邻居（LLDP/MAC 泛洪，快照 {topo.generated or '未知时间'}）："]
    for lk in links[:12]:
        other = lk.b_device if lk.a_device.lower() == target else lk.a_device
        my_if = lk.a_interface if lk.a_device.lower() == target else lk.b_interface
        peer_if = lk.b_interface if lk.a_device.lower() == target else lk.a_interface
        lines.append(f"  - {my_if or '?'} ↔ {other}"
                     f"{f' 的 {peer_if}' if peer_if else ''}"
                     f"（{lk.evidence}/{lk.confidence}）")
    if parent and parent.lower() != target:
        lines.append(f"- 上级设备（生成树推导）：{parent}")
    text = "\n".join(lines)
    return text[:max_chars]


def _default_chat(messages: list[dict]) -> str:
    """默认的 LLM 调用：用当前激活提供方，非流式、不打扰 stdout。"""
    from core.llm_client import stream_chat

    result = stream_chat(messages, tools=None, show_thinking=False,
                         show_answer=False, timeout=180)
    return result.content or ""


def generate_wiki_markdown(name: str, config: str, topology: str = "",
                           chat=None) -> str:
    """让模型根据当前配置 + 拓扑信息生成说明手册（只含 WIKI_TOPICS 两个小节）。

    chat 可注入（测试用）；默认走当前激活提供方。返回原始生成文本。
    """
    user = (
        f"设备名：{name}\n\n"
        f"———— 实测拓扑信息（可能为空）————\n{topology or '（无实测拓扑数据）'}\n\n"
        f"———— display current-configuration 回显（可能截断）————\n"
        f"{(config or '').strip()[:6000] or '（未抓到配置）'}\n\n"
        "请按系统要求生成两个一级小节。"
    )
    chat = chat or _default_chat
    return chat([
        {"role": "system", "content": WIKI_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]) or ""


def _split_wiki_topics(text: str) -> dict[str, str]:
    """把模型输出按 WIKI_TOPICS 拆成 {小节名: 正文}；缺失的小节不出现。"""
    out: dict[str, str] = {}
    current = ""
    buf: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if current:
                out[current] = "\n".join(buf).strip()
            matched = next((t for t in WIKI_TOPICS
                            if title == t or title.endswith(t)), None)
            current = matched or ""
            buf = []
            continue
        if current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf).strip()
    return {k: v for k, v in out.items() if v}


def wiki_enrich(name: str, config: str, topology: str = "",
                chat=None, session: str = "") -> dict:
    """新设备建档后的 Wiki 化：生成说明手册并写进「拓扑关系/配置基线」小节。

    返回 {"ok", "written": [小节名], "note"}。生成失败/内容为空时不动手册
    （骨架仍在，模型可稍后手工 update_device_manual_section 补）。
    """
    note = ""
    try:
        raw = generate_wiki_markdown(name, config, topology, chat=chat)
    except Exception as e:  # noqa: BLE001  LLM 失败不阻断建档
        return {"ok": False, "written": [],
                "note": f"Wiki 生成调用失败：{type(e).__name__}: {e}"}
    if not raw.strip():
        return {"ok": False, "written": [], "note": "Wiki 生成返回空内容"}
    topics = _split_wiki_topics(raw)
    if not topics:
        # 模型没按格式输出：整篇塞进「拓扑关系」当兜底，好过丢掉
        topics = {WIKI_TOPICS[0]: raw.strip()[:4000]}
        note = "模型输出未按小节格式，已整篇写入拓扑关系小节"
    written = []
    for topic in WIKI_TOPICS:
        body = topics.get(topic)
        if not body:
            continue
        try:
            update_section(name, topic, body, mode="replace", session=session)
            written.append(topic)
        except (ManualError, OSError) as e:
            note = f"{note}；写入 {topic} 失败：{e}".strip("；")
    return {"ok": bool(written), "written": written, "note": note}


# ---------------------------------------------------------------- 命令历史

def append_history(name: str, command: str, result: str = "", *, transport: str = "",
                   target: str = "", level: str = "", confirmed: bool = False,
                   executed: bool = False, extra: str = "", session: str = "") -> str:
    """追加一条命令历史（工具层自动调用，确定性记录，不依赖模型自觉）"""
    try:
        p = history_path(name, session)
    except ManualError:
        return ""
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "device": name,
        "transport": transport,
        "target": target,
        "command": command,
        "level": level,
        "confirmed": bool(confirmed),
        "executed": bool(executed),
        "result": (result or "")[:RESULT_MAX_CHARS],
    }
    if extra:
        record["extra"] = extra[:500]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(p), _FILE_LOCK:
            if p.exists() and p.stat().st_size > HISTORY_MAX_BYTES:
                return ""       # 超限就不再写，避免失控增长
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return ""
    return str(p)


def tail_history(name: str, n: int = 10, session: str = "") -> list[dict]:
    if n <= 0:
        return []
    p = history_path(name, session)
    if not p.is_file():
        return []
    rows: list[dict] = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-n:]


def tail_history_merged(names: list[str], n: int = 10,
                        session: str = "") -> list[dict]:
    """按**多个名字**读同一台设备的历史并合并（按时间排序）。

    为什么需要：设备身份会变。首次访问时可能还没绑定名字，历史落在地址兜底名
    （`192.168.1.1_2001`）下；后来建档绑定成 `SW1`，新历史进 `SW1/`。
    只看 canonical 名就会丢掉绑定之前那段记录——而那往往正是「第一次怎么配的」。
    因此解析出设备后把它的全部别名目录一起读，去重后按时间给最近 n 条。
    """
    if n <= 0:
        return []
    merged: list[dict] = []
    seen: set[str] = set()
    for name in names:
        try:
            safe = safe_name(name)
        except ManualError:
            continue                    # 形如 host:port 的别名不是合法目录名，跳过
        if safe.lower() in seen:
            continue
        seen.add(safe.lower())
        try:
            merged.extend(tail_history(safe, n, session))
        except (ManualError, OSError):
            continue
    merged.sort(key=lambda r: str(r.get("time") or ""))
    return merged[-n:]


def history_only_devices(session: str = "") -> list[str]:
    """只有命令历史、还没有手册的设备目录名（旧版命名不一致的产物）。

    必须能被查询到：否则模型 `list_device_manuals` 看不见它，会以为设备从没接触过。
    """
    root = ss.session_dir(session or None) / "skill"
    if not root.is_dir():
        return []
    out: list[str] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if (d / "history.jsonl").is_file() and not (d / "SKILL.md").is_file():
            out.append(d.name)
    return out


# ---------------------------------------------------------------- 清单

def _history_lines(p: Path) -> int:
    if not p.is_file():
        return 0
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def list_manuals(session: str = "") -> list[dict]:
    """已建档设备一览（默认只看**当前会话**，供模型/界面查看哪些设备有自己的手册）"""
    out: list[dict] = []
    root = ss.session_dir(session or None) / "skill"
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        f = d / "SKILL.md"
        if not (d.is_dir() and f.is_file()):
            continue
        try:
            stat = f.stat()
        except OSError:
            continue
        out.append({
            "name": d.name,
            "bytes": stat.st_size,
            "updated": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "history_lines": _history_lines(d / "history.jsonl"),
        })
    return out


def sessions_overview() -> list[dict]:
    """所有会话的技能分布（含当前会话标记），供 list_session_skills 工具使用。"""
    out: list[dict] = []
    for s in ss.list_sessions():
        row = dict(s)
        # 每个会话补一份设备明细：有手册的写手册大小/历史条数，
        # 只有历史没有手册的（旧版两套命名不一致的产物）也列出来，标「仅历史」
        details = []
        root = ss.session_dir(s["sid"]) / "skill"
        manuals = {m["name"]: m for m in list_manuals(s["sid"])}
        names = set(manuals)
        if root.is_dir():
            for d in root.iterdir():
                if d.is_dir() and d.name not in names:
                    names.add(d.name)
        for name in sorted(names):
            m = manuals.get(name)
            if m:
                details.append(f"{name}（手册 {max(1, m['bytes'] // 1024)}KB，"
                               f"历史 {m['history_lines']} 条）")
            else:
                details.append(f"{name}（仅历史 {_history_lines(root / name / 'history.jsonl')} 条）")
        row["detail"] = details
        out.append(row)
    return out


# ---------------------------------------------------------------- 提示词注入

def _extract_meta(text: str) -> dict:
    """从手册正文里抠出型号/角色/拓扑摘要/一条注意事项（供系统提示词做紧凑摘要）。

    注意事项按**出现顺序取最后一条**：新建手册时它是型号基线的最后一条；
    模型在本对话里学过东西之后，它就是最新沉淀的那条——摘要要突出
    「最近学到什么」，而不是每台设备都重复同一句基线。

    拓扑摘要取「拓扑关系」小节的第一条实质内容（邻居/角色一句话），
    让模型开局就知道这台设备挂在哪，无需每次都 read_device_manual 全文。

    候选行的取舍： bullet（`- `）优先收录；模型用散文写的坑（不以 `-` 开头的
    短行）也收，避免「写了但摘要里看不见」；代码块 / 标题 / 占位句跳过。
    """
    meta: dict = {"model": "", "role": "", "tip": "", "topo": ""}
    cands: list[str] = []
    section = ""            # 当前所处的一级小节名
    in_code = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            title = s[2:].strip()
            section = ("注意事项" if title.endswith("注意事项")
                       else "拓扑关系" if title.endswith("拓扑关系")
                       else "")
            in_code = False
            continue
        if section == "拓扑关系":
            # 只取邻居/上级这类结论行；快照时间戳行与占位句跳过
            if s.startswith("- 实测邻居"):
                meta["topo"] = s
            elif s.startswith("- 上级设备") and not meta["topo"]:
                meta["topo"] = s
            elif s.startswith("  - ") and not meta["topo"]:
                meta["topo"] = s.strip()[2:]
            continue
        if not section:
            if s.startswith("- 型号：") and not meta["model"]:
                meta["model"] = s.split("：", 1)[-1].strip()
            elif s.startswith("- 角色：") and not meta["role"]:
                meta["role"] = s.split("：", 1)[-1].strip()
            continue
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s or s[0] in "#（>`":
            continue
        cand = s[2:].strip() if s.startswith("- ") else s
        if cand and not cand.startswith("（执行过程中发现的坑") and len(cand) <= 100:
            cands.append(cand)
    if cands:
        meta["tip"] = cands[-1]
    return meta


def context_for_model(max_devices: int = 8, max_chars: int = 4000) -> str:
    """当前会话已积累的设备技能摘要（注入系统提示词）。

    为什么是「直注提示词」而不是「进向量库检索」：技能已按会话隔离，而向量库
    索引是全局单份——把手册塞进索引，切换会话后旧会话的手册仍会被检索出来，
    正好破坏隔离；每次切换都重建索引又要先删后建，期间检索会拿到空库。
    因此手册改成「当前会话直注 + 按需 read_device_manual 读全文」：
    隔离是确定的，切换是瞬时的，也不占用检索名额。

    没有技能时返回空串——不往提示词里塞噪声。
    """
    manuals = list_manuals()
    if not manuals:
        return ""
    sid = ss.current()
    lines = [f"【本会话已积累的设备技能 · 会话 {sid}】",
             "（仅当前对话可见；其他对话的设备记忆相互隔离，请勿假设别处也有）"]
    used = sum(len(x) for x in lines)
    listed = 0
    for i, m in enumerate(manuals):
        if listed >= max_devices:
            break
        meta = _extract_meta(read_manual(m["name"]))
        head = (f"- {m['name']}"
                + (f"｜{meta['model']}" if meta["model"] and "待确认" not in meta["model"] else "")
                + (f"｜{meta['role']}" if meta["role"] and "待确认" not in meta["role"] else "")
                + f"｜手册 {max(1, m['bytes'] // 1024)}KB｜历史 {m['history_lines']} 条"
                + f"｜更新 {m['updated']}")
        tip = ""
        if meta["tip"]:
            tip = "    坑：" + (meta["tip"][:110] + "…" if len(meta["tip"]) > 110 else meta["tip"])
        topo = ""
        if meta.get("topo"):
            topo = "    拓扑：" + (meta["topo"][:110] + "…" if len(meta["topo"]) > 110 else meta["topo"])
        if used + len(head) + len(tip) + len(topo) + 3 > max_chars:
            break                      # 字符预算用尽，剩下的靠工具按需读
        lines.append(head)
        if topo:
            lines.append(topo)
        if tip:
            lines.append(tip)
        used += len(head) + len(tip) + len(topo) + 3
        listed += 1
    if listed < len(manuals):
        lines.append(f"（还有 {len(manuals) - listed} 台设备的技能未列出，"
                     f"用 read_device_manual 按需读取）")
    lines.append("操作某台设备前可 read_device_manual 读全文；"
                 "验证有效的配置用 update_device_manual_section 沉淀回本会话。")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 旧版迁移

def migrate_legacy(session: str = "legacy-global", force: bool = False) -> dict:
    """把旧版全局技能（`skills/` + `data/device_history/`）搬进某个会话。

    旧布局是所有对话共用一份，与「一个对话一套技能」冲突。这里做**一次性复制**
    （不删源目录）：搬完用户确认新布局没问题，再自行决定是否清理旧目录。

    两边设备名不一定对得上（历史里有 `SW1.jsonl` 而手册里叫 `LSW1` 是常事），
    因此手册与历史分别扫描：只有历史没有手册的设备也照样搬，技能目录里存
    history.jsonl，模型下次接触它时能看到以前的命令记录。

    Returns:
        {"session": sid, "migrated": [...], "history_only": [...],
         "skipped": [...], "missing": bool}
    """
    report = {"session": session, "migrated": [], "history_only": [],
              "skipped": [], "missing": True}
    if not SKILLS_DIR.is_dir() and not HISTORY_DIR.is_dir():
        return report
    report["missing"] = False

    def _copy(src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

    # ① 手册（连同同名历史）
    if SKILLS_DIR.is_dir():
        for d in sorted(SKILLS_DIR.iterdir()):
            if not d.is_dir():
                continue
            try:
                src_manual = d / "SKILL.md"
                if not src_manual.is_file():
                    continue
                dst_manual = manual_path(d.name, session)
                if dst_manual.is_file() and not force:
                    report["skipped"].append(d.name)
                    continue
                _copy(src_manual, dst_manual)
                src_hist = HISTORY_DIR / f"{d.name}.jsonl"
                if src_hist.is_file():
                    _copy(src_hist, history_path(d.name, session))
                report["migrated"].append(d.name)
            except (OSError, ManualError) as e:
                report["skipped"].append(f"{d.name}（{type(e).__name__}: {e}）")

    # ② 只有历史、没有手册的设备（旧版两套命名不一致的产物）
    if HISTORY_DIR.is_dir():
        for src_hist in sorted(HISTORY_DIR.glob("*.jsonl")):
            name = src_hist.stem
            try:
                dst_hist = history_path(name, session)
                if dst_hist.is_file():
                    continue                     # ① 已搬过或目标已有
                _copy(src_hist, dst_hist)
                report["history_only"].append(name)
            except (OSError, ManualError) as e:
                report["skipped"].append(f"{name}.jsonl（{type(e).__name__}: {e}）")
    return report


# ---------------------------------------------------------------- CLI

def _main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m core.device_manual",
        description="设备技能（按会话隔离）查看与旧版迁移")
    ap.add_argument("--current", action="store_true", help="显示当前会话与技能目录")
    ap.add_argument("--sessions", action="store_true", help="列出所有会话及其设备技能")
    ap.add_argument("--migrate-legacy", action="store_true",
                    help="把旧版 skills/ 与 data/device_history/ 复制进一个会话")
    ap.add_argument("--session", default="legacy-global",
                    help="迁移目标会话标识（默认 legacy-global）")
    ap.add_argument("--force", action="store_true", help="迁移时覆盖已存在的目标手册")
    args = ap.parse_args(argv)

    if args.migrate_legacy:
        rep = migrate_legacy(args.session, force=args.force)
        if rep["missing"]:
            print(f"没有找到旧版技能目录 {SKILLS_DIR} / {HISTORY_DIR}，无需迁移")
            return 0
        print(f"已迁移 {len(rep['migrated'])} 台设备（手册+历史）→ session/{rep['session']}/skill/")
        for n in rep["migrated"]:
            print(f"  ✓ {n}")
        if rep["history_only"]:
            print(f"另迁移 {len(rep['history_only'])} 台只有历史没有手册的设备："
                  + ", ".join(rep["history_only"]))
        for n in rep["skipped"]:
            print(f"  - 跳过 {n}（目标已存在，加 --force 可覆盖）")
        print("旧目录未删除；确认新布局无误后可自行清理 skills/ 与 data/device_history/")
        return 0

    if args.sessions:
        print(f"会话根目录：{ss.SESSIONS_DIR}")
        rows = sessions_overview()
        if not rows:
            print("  （还没有任何会话）")
        for s in rows:
            mark = "← 当前" if s["current"] else ""
            devs = "、".join(s["detail"]) or "（无设备技能）"
            print(f"  {s['sid']:30} {s['updated']}  {s['files']:3d} 个文件  {mark}")
            print(f"      {devs}")
        return 0

    print(ss.describe())
    manuals = list_manuals()
    if not manuals:
        print("  本会话暂无设备技能（首次接触设备时会自动建档）")
    for m in manuals:
        print(f"  [{m['name']}] {m['bytes']} 字节，更新于 {m['updated']}，"
              f"历史 {m['history_lines']} 条")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
