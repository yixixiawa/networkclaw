"""设备手册与命令历史：**运行期由本地模型自建自维护**的资产（不是代码里的固定内容）。

设计原则（按用户要求）：
    · 内容不写死在仓库里——手理由本地模型在首次接触设备时自己建档、配置成功后自己沉淀；
    · 文件只落本机工作目录（源码模式=项目根，打包模式=exe 旁边），`skills/` 已进 .gitignore；
    · 本模块只做「文件读写 + 结构规范」，不做任何内容生成——内容由模型（经 MCP 工具）提供。

两个产物：
    skills/<设备名>/SKILL.md           设备手册（骨架固定，内容由模型填）
    data/device_history/<设备名>.jsonl 逐条命令历史（工具层自动追加，确定性，不依赖模型自觉）

安全约束：
    · 设备名做白名单过滤（禁止路径分隔符 / 相对路径），杜绝越权写文件；
    · 手册与历史都有体积上限，避免模型反复追加把文件写爆。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from core.paths import BASE_DIR

SKILLS_DIR = BASE_DIR / "skills"
HISTORY_DIR = BASE_DIR / "data" / "device_history"

MANUAL_MAX_BYTES = 256 * 1024     # 单份手册上限
HISTORY_MAX_BYTES = 4 * 1024 * 1024
RESULT_MAX_CHARS = 4000           # 单条历史里回显截断长度

SECTIONS = ("设备信息", "常用配置", "注意事项")
_NAME_RE = re.compile(r"^[\w\-\u4e00-\u9fff]{1,40}$")   # 字母数字下划线连字符与中文


class ManualError(ValueError):
    """设备名非法 / 内容超限等可读错误"""


def safe_name(name: str) -> str:
    """校验设备名（既当文件名也当目录名），非法直接报错"""
    name = (name or "").strip()
    if not name:
        raise ManualError("设备名不能为空")
    if not _NAME_RE.match(name) or name in (".", ".."):
        raise ManualError(
            f"设备名「{name}」不合法：只能用中英文、数字、下划线、连字符（1-40 字）")
    return name


def manual_path(name: str) -> Path:
    return SKILLS_DIR / safe_name(name) / "SKILL.md"


def history_path(name: str) -> Path:
    return HISTORY_DIR / f"{safe_name(name)}.jsonl"


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

# 常用配置

（配置验证有效后，由模型把命令序列与适用场景写在这里）

# 注意事项

{tips_body}
"""


# ---------------------------------------------------------------- 读写

def read_manual(name: str) -> str:
    p = manual_path(name)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def save_manual(name: str, content: str) -> int:
    """整篇写入（模型完全重写时用），返回字节数"""
    if not (content or "").strip():
        raise ManualError("手册内容不能为空")
    data = content.encode("utf-8")
    if len(data) > MANUAL_MAX_BYTES:
        raise ManualError(f"手册过大（{len(data)} 字节 > {MANUAL_MAX_BYTES}），请精简后重写")
    p = manual_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return len(data)


def ensure_manual(name: str, **meta) -> tuple[str, bool]:
    """手册不存在则用骨架建档。返回 (手册内容, 是否新建)"""
    text = read_manual(name)
    if text:
        return text, False
    text = skeleton(name, **meta)
    save_manual(name, text)
    return text, True


def update_section(name: str, section: str, text: str,
                   mode: str = "append", title: str = "") -> str:
    """把内容写入指定小节（小节不存在就创建），返回处理后的整篇手册。

    Args:
        section: 目标小节名，通常是 设备信息 / 常用配置 / 注意事项
        text: 要写入的内容（命令序列、注意事项等）
        mode: append（追加，默认）或 replace（替换该小节全部内容）
        title: 追加时可选的小标题，插入为 `## <title>`
    """
    section = (section or "").strip() or "常用配置"
    if "\n#" in section or len(section) > 30:
        raise ManualError("小节名不合法（应为 30 字以内的短语，不含换行）")
    text = (text or "").strip()
    if not text:
        raise ManualError("要写入的内容不能为空")

    current = read_manual(name) or skeleton(name)
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
    save_manual(name, new_text.strip() + "\n")
    return read_manual(name)


# ---------------------------------------------------------------- 命令历史

def append_history(name: str, command: str, result: str = "", *, transport: str = "",
                   target: str = "", level: str = "", confirmed: bool = False,
                   executed: bool = False, extra: str = "") -> str:
    """追加一条命令历史（工具层自动调用，确定性记录，不依赖模型自觉）"""
    try:
        p = history_path(name)
    except ManualError:
        return ""
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and p.stat().st_size > HISTORY_MAX_BYTES:
        return ""       # 超限就不再写，避免失控增长
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
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return ""
    return str(p)


def tail_history(name: str, n: int = 10) -> list[dict]:
    p = history_path(name)
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
    return rows[-max(1, n):]


# ---------------------------------------------------------------- 清单

def list_manuals() -> list[dict]:
    """已建档设备一览（供模型/界面查看哪些设备有自己的手册）"""
    out: list[dict] = []
    if not SKILLS_DIR.is_dir():
        return out
    for d in sorted(SKILLS_DIR.iterdir()):
        f = d / "SKILL.md"
        if not (d.is_dir() and f.is_file()):
            continue
        try:
            stat = f.stat()
        except OSError:
            continue
        hist = history_path(d.name)
        lines = 0
        if hist.is_file():
            try:
                with open(hist, encoding="utf-8", errors="replace") as fh:
                    lines = sum(1 for _ in fh)
            except OSError:
                lines = 0
        out.append({
            "name": d.name,
            "bytes": stat.st_size,
            "updated": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "history_lines": lines,
        })
    return out
