"""会话级设备技能：**一个对话一套 skill，对话之间的设备记忆互不串味**。

背景（用户明确要求）：
    最早的版本把所有对话的设备手册统一放在 `skills/<设备名>/SKILL.md`。结果是
    对话 A 里给 SW1 踩过的坑、写下的命令序列，会在对话 B 检索知识库时被原样
    捞出来——模型把「另一段对话里的结论」当成本对话的经验，改错了还查不出原因。

因此技能改为按会话隔离，布局由用户指定：

    session/<会话标识>/skill/<设备名>/SKILL.md          设备手册（模型自建自维护）
    session/<会话标识>/skill/<设备名>/history.jsonl     该设备在本对话里的命令历史
    session/.current                                   当前会话指针（跨进程共享）

「当前会话」怎么在多个进程间保持一致：
    主程序（CLI / GUI / 批量实验）在**开出一个对话时**调用 `use_session(sid)`，
    它做两件事——把 sid 写进 `session/.current`，并同步 `core.run_log` 的会话标识
    （运行日志与技能从此同会话、同命运）。MCP 服务端是**独立子进程**，它们每次
    工具调用前读 `session/.current`（按 mtime 缓存，几乎零成本），因此 GUI 里
    切换会话后，服务端立刻跟着切，不需要重启连接。

    解析优先级：本进程 `set_session` 钉过的 sid > `session/.current` > 环境变量
    NETWORKCLAW_SESSION（父进程派生时透传，供没有指针文件的场景兜底）> "default"。

    已知边界：同时开两个 CLI 会互相覆盖 `.current`（个人单用户工具，可接受）；
    需要并行跑又不互相干扰时，用 NETWORKCLAW_SESSION 给每个进程钉死不同 sid。

安全约束：
    · 会话标识与设备名都走 `safe_name()` 白名单（禁路径分隔符与相对路径），
      杜绝越权读写——这两个名字都会直接当目录名用。
"""
from __future__ import annotations

import datetime
import os
import re
import threading
from pathlib import Path

from core.paths import BASE_DIR

SESSIONS_DIR = BASE_DIR / "session"          # 所有会话的技能根目录
ENV_VAR = "NETWORKCLAW_SESSION"              # 环境变量兜底（父进程派生时透传）
DEFAULT_SID = "default"

_NAME_RE = re.compile(r"^[\w\-\u4e00-\u9fff.]{1,80}$")   # 中英文数字下划线连字符点
_FORBIDDEN = (".", "..")
# Windows 保留设备名：拿它当目录名，mkdir 会直接失败（WinError 123），
# 且报错信息跟「权限不足」很像，很难排查。这里在建目录前就拒掉。
_RESERVED = ({"con", "prn", "aux", "nul"}
             | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)})

_LOCK = threading.Lock()
_pinned: str | None = None                   # 本进程显式钉过的会话
_cache: dict = {"sid": DEFAULT_SID, "stamp": None}


def _pointer_file() -> Path:
    """当前会话指针文件路径（每次现算，便于测试替换 SESSIONS_DIR 后立即生效）。"""
    return SESSIONS_DIR / ".current"


class SessionError(ValueError):
    """会话标识 / 设备名非法等可读错误"""


def is_reserved(name: str) -> bool:
    """是否是 Windows 保留设备名（CON/PRN/AUX/NUL/COM1-9/LPT1-9）。

    这类名字**可以**出现在业务语义里（串口号就叫 COM3），但不能当目录名。
    调用方据此决定「加后缀」而不是「直接报错」，避免把 COM3 的历史静默丢掉。
    """
    return (name or "").strip().lower() in _RESERVED


def safe_name(name: str, what: str = "名称") -> str:
    """校验一个要当目录名用的字符串（会话标识或设备名），非法直接报错。"""
    s = (name or "").strip()
    if not s:
        raise SessionError(f"{what}不能为空")
    if not _NAME_RE.match(s) or s in _FORBIDDEN or s.startswith("."):
        raise SessionError(
            f"{what}「{s}」不合法：只能用中英文、数字、下划线、连字符、点（1-80 字），"
            f"且不能以点开头")
    if s.lower() in _RESERVED:
        raise SessionError(f"{what}「{s}」是系统保留名（CON/COM1/LPT1 等），不能用作目录名")
    return s


def new_sid(prefix: str = "cli") -> str:
    """生成一个新会话标识：`<前缀>-<时间戳>-<随机后缀>`。

    带随机后缀是为了避免「同一秒内开两个对话」撞名；后缀同时让人一眼看出
    这不是给人读的名字（GUI 用的是 uuid，实验用的是「编号-实验名」）。
    """
    import secrets

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{safe_name(prefix, '会话前缀')}-{stamp}-{secrets.token_hex(2)}"


def _read_pointer() -> str:
    """读 `session/.current`（带 mtime 缓存；文件被别的进程改写过会自动失效）。"""
    fp = _pointer_file()
    try:
        st = fp.stat()
        stamp = (st.st_mtime_ns, st.st_size, getattr(st, "st_ino", 0))
    except OSError:
        return ""
    with _LOCK:
        if _cache.get("stamp") == stamp and _cache.get("sid"):
            return _cache["sid"]
    try:
        sid = fp.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    sid = sid.splitlines()[0].strip() if sid else ""
    if not sid:
        return ""
    try:
        sid = safe_name(sid, "指针中的会话标识")
    except SessionError:
        return ""
    with _LOCK:
        _cache["sid"], _cache["stamp"] = sid, stamp
    return sid


def set_session(sid: str) -> Path:
    """把当前会话钉到 sid：写指针文件 + 记进本进程，返回该会话的技能目录。"""
    global _pinned
    sid = safe_name(sid, "会话标识")
    d = SESSIONS_DIR / sid
    d.mkdir(parents=True, exist_ok=True)
    # 指针文件先写临时再替换，避免半行内容被并发读到
    fp = _pointer_file()
    tmp = fp.with_name(fp.name + ".tmp")
    tmp.write_text(sid + "\n", encoding="utf-8")
    os.replace(tmp, fp)
    with _LOCK:
        _pinned = sid
        _cache["sid"], _cache["stamp"] = sid, None
    os.environ[ENV_VAR] = sid
    return d


def use_session(sid: str) -> Path:
    """一步切换「技能 + 运行日志」到同一会话（GUI 切会话 / CLI 启动 / 实验切题用）。

    运行日志与技能分开两个模块管理，但**必须是同一个 sid**：否则「本对话的
    设备记忆」会被拆成两半，检索摘要时对不上。
    """
    d = set_session(sid)
    try:
        from core import run_log

        run_log.set_session(sid)
    except Exception:
        pass          # 日志模块不可用不能阻断技能切换
    return d


def current() -> str:
    """当前会话标识（见模块 docstring 的优先级说明）。"""
    if _pinned:
        return _pinned
    sid = _read_pointer()
    if sid:
        return sid
    env = (os.environ.get(ENV_VAR) or "").strip()
    if env:
        try:
            return safe_name(env, "环境变量会话标识")
        except SessionError:
            return DEFAULT_SID
    return DEFAULT_SID


def session_dir(sid: str | None = None) -> Path:
    """会话根目录（不存在也不会报错，由写入方按需创建）。"""
    resolved = safe_name(sid, "会话标识") if sid is not None else current()
    return SESSIONS_DIR / resolved


def skill_dir(device: str, sid: str | None = None) -> Path:
    """某会话里某台设备的技能目录：`session/<sid>/skill/<设备名>`"""
    return session_dir(sid) / "skill" / safe_name(device, "设备名")


def manual_path(device: str, sid: str | None = None) -> Path:
    return skill_dir(device, sid) / "SKILL.md"


def history_path(device: str, sid: str | None = None) -> Path:
    return skill_dir(device, sid) / "history.jsonl"


def list_sessions() -> list[dict]:
    """所有会话一览（按最近更新排序），供「我有哪些对话的记忆」这类查看。

    只读目录结构，不解析手册内容；`.` 开头的（如 .current）自动跳过。
    """
    out: list[dict] = []
    if not SESSIONS_DIR.is_dir():
        return out
    cur = current()
    for d in sorted(SESSIONS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        try:
            files = [p for p in d.rglob("*") if p.is_file()]
        except OSError:
            continue
        if not files:
            continue
        mtimes = [p.stat().st_mtime for p in files]
        out.append({
            "sid": d.name,
            "devices": sorted({p.parent.name for p in files
                               if p.parent.parent.name == "skill"}),
            "files": len(files),
            "bytes": sum(p.stat().st_size for p in files),
            "updated": datetime.datetime.fromtimestamp(max(mtimes)).strftime("%Y-%m-%d %H:%M"),
            "current": d.name == cur,
        })
    out.sort(key=lambda x: (not x["current"], x["updated"]), reverse=True)
    return out


def describe() -> str:
    """给人看的一行说明（CLI / 日志用）。"""
    sid = current()
    return f"当前会话 {sid}（技能目录 {session_dir(sid)}）"


if __name__ == "__main__":
    print(f"会话根目录：{SESSIONS_DIR}")
    print(describe())
    for s in list_sessions():
        mark = "← 当前" if s["current"] else ""
        devs = ", ".join(s["devices"]) or "（无设备技能）"
        print(f"  {s['sid']:28} {s['updated']}  {s['files']:3d} 个文件  "
              f"{s['bytes'] / 1024:7.1f} KB  {devs} {mark}")
