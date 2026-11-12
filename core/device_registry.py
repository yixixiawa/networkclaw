"""设备登记与在线状态：把「智能体访问过的设备」集中管理起来，供 GUI 展示。

两个数据来源合并出一个设备清单：

1. data/device_inventory.json —— 人工维护的种子清单（device-config-recorder skill 维护），
   含设备名 / 端口映射 / 型号 / 手册路径。本模块只读，绝不改写它。
2. data/device_access.json    —— 运行期自动登记：MCP 工具（Telnet / 串口）每次
   成功连上设备就记一笔（first_seen / last_seen / 次数）。清单之外新访问到的
   设备（比如用户临时给了一个 IP）也会出现在这里，从而「访问过就能看到」。

在线判定（probe_all，只读探测，绝不下发命令）：
    telnet  → core.device_conn.probe_tcp(host, port)
    serial  → 串口是否仍在本机枚举列表里（pyserial list_ports）
探测在线程池里并发跑，整轮耗时 ≈ 最慢一个，而不是累加。

跨进程说明：MCP 服务端是独立子进程，登记走「读-合并-原子替换写」，
极端并发下最多丢一条记录，可接受；文件损坏时自动备份后重建。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from core.paths import BASE_DIR
from core.file_lock import file_lock

INVENTORY_PATH = BASE_DIR / "data" / "device_inventory.json"
ACCESS_PATH = BASE_DIR / "data" / "device_access.json"

_LOCK = threading.Lock()
PROBE_TIMEOUT = 2.0        # 单设备 TCP 探测超时（秒）
PROBE_WORKERS = 16         # 并发探测线程数


# ---------------------------------------------------------------- 读写

def _norm(s) -> str:
    """统一比较用的归一化：去空白 + 小写"""
    return str(s or "").strip().lower()


def _sanitize_name(raw: str) -> str:
    """把 host:port / 任意字符串变成合法目录名（safe_name 的字符集）"""
    return re.sub(r"[^\w\-\u4e00-\u9fff.]", "_", str(raw or ""))[:80] or "unknown-device"


_SAFE_RE = re.compile(r"^[\w\-\u4e00-\u9fff.]{1,80}$")


def _canonical_name(d: dict) -> str:
    """设备身份用的 canonical 名：必须是**能直接当目录名**的字符串。

    访问登记没绑定名字时，`list_devices()` 给的是 `host:port`（展示用），
    冒号不是合法目录名，直接拿去查历史会抛 ManualError。这里统一退化成
    `resolve_name()` 那套地址兜底名（`192.168.1.1_2001`），保证
    「清单里看到的名字 = 历史目录名 = 可直接查询的名字」。
    """
    raw = str(d.get("name") or "").strip()
    if raw and _SAFE_RE.match(raw) and not raw.startswith("."):
        # 保留设备名（COM3/LPT1…）虽然过得了正则，但当不了目录名，统一加后缀
        return _serial_dirname(raw)
    if (d.get("transport") or "") == "serial":
        return _serial_dirname(_sanitize_name(
            d.get("serial_port") or raw or d.get("key")))
    if d.get("host"):
        return _sanitize_name(f"{d['host']}_{d['port']}" if d.get("port") else d["host"])
    return _sanitize_name(raw or d.get("key") or "unknown-device")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception:
        # 损坏：备份后当不存在处理，别让一条坏记录拖垮整个功能
        try:
            path.replace(path.with_suffix(".corrupt.bak"))
        except OSError:
            pass
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- 登记（MCP 服务端调用）

def _device_key(transport: str, host: str = "", port: int = 0,
                serial_port: str = "") -> str:
    if transport == "serial":
        return f"serial:{serial_port}"
    return f"{host}:{port}"


def record_access(transport: str, host: str = "", port: int = 0,
                  serial_port: str = "", name: str = "") -> None:
    """记一笔「访问过该设备」。任何失败都静默——登记绝不能影响工具执行。

    Args:
        transport: "telnet" 或 "serial"
        host/port: telnet 目标
        serial_port: 串口号（如 COM3）
        name: 可选的设备名（不知道就留空，展示时用地址代替）
    """
    try:
        with file_lock(ACCESS_PATH), _LOCK:
            data = _read_json(ACCESS_PATH, {"devices": {}})
            devices: dict = data.setdefault("devices", {})
            key = _device_key(transport, host, port, serial_port)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = devices.get(key) or {}
            entry.update({
                "transport": transport,
                "host": host or entry.get("host", ""),
                "port": port or entry.get("port", 0),
                "serial_port": serial_port or entry.get("serial_port", ""),
            })
            if name and not entry.get("name"):
                entry["name"] = name
            entry["last_seen"] = now
            entry["count"] = int(entry.get("count", 0)) + 1
            entry.setdefault("first_seen", now)
            devices[key] = entry
            _write_json(ACCESS_PATH, data)
    except Exception:
        pass


def _unique_name(devices: dict, key: str, name: str,
                 port: int = 0, serial_port: str = "") -> str:
    """给 key 找一个不与**其他地址**重名的名字。

    为什么必须去重：手册与命令历史都以设备名当目录名（`session/<sid>/skill/<名>/`），
    两台设备绑同一个名字，历史就会写进同一个 history.jsonl——之后
    `recent_device_history("SW1")` 会把另一台设备的记录当成这台的经验，
    跟「一个对话一套技能」要防的串味是同一类事故。
    """
    base = (name or "").strip()
    if not base:
        return base
    taken = {_norm(e.get("name")) for k, e in devices.items()
             if k != key and _norm(e.get("name"))}
    if _norm(base) not in taken:
        return base
    suffix = str(port) if port else (serial_port or "2")
    candidate = f"{base}-{suffix}"
    i = 2
    while _norm(candidate) in taken:
        candidate = f"{base}-{suffix}-{i}"
        i += 1
        if i > 50:                      # 兜底：极端情况下加随机后缀，绝不静默重名
            candidate = f"{base}-{uuid.uuid4().hex[:4]}"
            break
    return candidate


def bind_name(transport: str, name: str, host: str = "", port: int = 0,
              serial_port: str = "") -> str:
    """把设备名绑定到某个地址（模型为该设备建档时调用），返回**实际生效的名字**。

    绑定后，后续该地址的命令历史会自动归到这个名字的文件里，
    清单展示也用它代替裸地址。任何失败都静默（返回空串）。

    返回实际名字很重要：请求的名字若已被**另一个地址**占用，这里会自动加
    `-<端口>` 后缀，调用方必须拿返回值去建档，否则手册与历史会落到两个目录。
    """
    try:
        name = (name or "").strip()
        if not name:
            return ""
        # 绑定名会直接当目录名用：COM3 这类保留名先规范化成 COM3-serial，
        # 否则调用方拿返回值去建档时会被 safe_name 拒收（串口设备无法建档）。
        name = _serial_dirname(name)
        with file_lock(ACCESS_PATH), _LOCK:
            data = _read_json(ACCESS_PATH, {"devices": {}})
            devices: dict = data.setdefault("devices", {})
            key = _device_key(transport, host, port, serial_port)
            entry = devices.get(key) or {}
            name = _unique_name(devices, key, name, port=port, serial_port=serial_port)
            entry.update({
                "transport": transport,
                "host": host or entry.get("host", ""),
                "port": port or entry.get("port", 0),
                "serial_port": serial_port or entry.get("serial_port", ""),
                "name": name,
            })
            entry.setdefault("last_seen", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            entry.setdefault("count", 0)
            devices[key] = entry
            _write_json(ACCESS_PATH, data)
            return name
    except Exception:
        return ""


def _serial_dirname(name: str) -> str:
    """串口设备名要当**目录名**用（session/<sid>/skill/<名>/history.jsonl）。

    坑：COM1-COM9 / LPT1 等是 Windows 保留设备名，`session_skills.safe_name`
    会拒收——此前 `resolve_name` 兜底返回裸 "COM3"，导致 `append_history`
    静默返回空串，**串口命令历史从项目开始就没归档过**。
    处理：保留名加 `-serial` 后缀（COM3 → COM3-serial，合法且一眼看出通道）；
    其它非法字符走 `_sanitize_name` 清洗；已合法的名字（用户绑定的 "SW1"）原样返回，
    历史目录不漂移。
    """
    try:
        from core.session_skills import safe_name

        safe_name(name)
        return name
    except Exception:  # noqa: BLE001  非法名字分两类处理
        pass
    try:
        from core.session_skills import is_reserved

        if is_reserved(name):
            return f"{name}-serial"
    except Exception:  # noqa: BLE001
        pass
    return _sanitize_name(name)


def resolve_name(transport: str, host: str = "", port: int = 0,
                 serial_port: str = "") -> str:
    """把「地址」解析成设备名（命令历史归档用，确定性、不依赖模型）。

    优先级：访问登记里**绑定的名字** > 种子清单（host:port 匹配）> 地址兜底
    串口通道没有清单概念，直接用 COM 口号。

    绑定优先于种子清单：绑定是「某个实验/某次建档」显式指定到 host:port 的，
    语义最具体；而种子清单是人工维护的静态默认，换拓扑（端口映射变了）之后
    反而会错配（实测 192.168.1.179:2000 在清单里是 R1，实际跑的是 LSW1）。
    """
    if transport == "serial":
        sp = (serial_port or "").strip().upper()
        accesses = _read_json(ACCESS_PATH, {"devices": {}}).get("devices", {})
        entry = accesses.get(_device_key("serial", serial_port=sp)) or {}
        return _serial_dirname((entry.get("name") or sp or "unknown-serial").strip())

    accesses = _read_json(ACCESS_PATH, {"devices": {}}).get("devices", {})
    entry = accesses.get(_device_key("telnet", host, port)) or {}
    if entry.get("name"):
        return str(entry["name"]).strip()
    inventories = _inventory_devices()
    for d in inventories:
        if d["host"] == host and int(d["port"]) == int(port):
            return d["name"]
    raw = f"{host}_{port}" if port else (host or "unknown-device")
    return _sanitize_name(raw)


# ---------------------------------------------------------------- 设备身份解析
#
# 为什么需要这一层：
#   手册与历史按「设备名」落目录，而模型/用户嘴里的名字、清单里的名字、
#   访问登记里的名字、地址（host:port / COM3）经常不一致：
#     模型说 SW1，登记里是 LSW1；登记为空时名字退化成 `192.168.183.137_2001`；
#     用户直接给 `192.168.183.137:2001` 又会因为冒号不是合法目录名而报错。
#   结果就是「明明有历史，查出来 0 条」，模型据此以为没做过、然后重做一遍。
#   这里提供唯一的解析入口：把任意写法解析成**一个确定的设备身份**，
#   歧义时拒绝猜（返回候选），而不是随便挑一个写进别人的历史文件。

def identities(session: str = "") -> list[dict]:
    """当前可查询的设备身份表（种子清单 ∪ 访问登记 ∪ 会话技能目录）。

    每条含：name（canonical，可直接当目录名）/ key / transport / host / port /
    serial_port / aliases（该设备的全部已知写法）/ sources（registry / skill）。
    """
    rows: dict[str, dict] = {}
    for d in list_devices():
        rows[d["key"]] = {
            "key": d["key"],
            "name": _canonical_name(d),
            "display": d.get("name") or _display_name(d),
            "transport": d.get("transport", "telnet"),
            "host": d.get("host", ""),
            "port": int(d.get("port", 0) or 0),
            "serial_port": d.get("serial_port", ""),
            "sources": {"registry"},
        }

    # 会话技能目录：读写都落在这里，名字必须能被解析到，否则查不到自己刚写的文件
    names: set[str] = set()
    try:
        from core import device_manual

        names = {m["name"] for m in device_manual.list_manuals(session)}
        names |= set(device_manual.history_only_devices(session))
    except Exception:  # noqa: BLE001  技能目录不可读不能拖垮设备清单
        names = set()

    by_name = {_norm(r["name"]): key for key, r in rows.items() if r.get("name")}
    for n in sorted(names):
        key = by_name.get(_norm(n))
        if key:
            rows[key]["sources"].add("skill")
        else:
            rows[f"skill:{n}"] = {
                "key": "", "name": n, "display": n, "transport": "", "host": "",
                "port": 0, "serial_port": "", "sources": {"skill"},
            }

    for r in rows.values():
        al: set[str] = {r["name"], r.get("display", "")}
        if r["key"]:
            al.add(r["key"])
            al.add(_sanitize_name(r["key"]))
        if r["host"]:
            al.add(r["host"])
            al.add(f"{r['host']}:{r['port']}" if r["port"] else r["host"])
        if r["port"]:
            al.add(str(r["port"]))
        if r["serial_port"]:
            al.add(r["serial_port"])
        r["aliases"] = sorted({a for a in al if str(a or "").strip()})
    return list(rows.values())


def session_devices(sid: str) -> list[dict]:
    """本会话出现过的设备（skill 目录里有手册或有命令历史），带注册表地址元数据。

    会话隔离的清单来源：`session/<sid>/skill/<设备>/`（SKILL.md / history.jsonl）——
    助手在本会话里真正连过并留档的设备才算数。命中后到全局注册表（identities）
    里找同名设备的地址元数据（host:port / 串口号），在线探测才有目标；
    只在 skill 目录出现、注册表查不到的设备也返回（key 为空，GUI 能列出但探不了）。
    """
    if not sid:
        return []
    try:
        from core import device_manual

        names = {m["name"] for m in device_manual.list_manuals(sid)}
        names |= set(device_manual.history_only_devices(sid))
    except Exception:  # noqa: BLE001  会话目录不可读 → 该会话暂无设备记录
        return []
    if not names:
        return []

    wanted = {_norm(n) for n in names if str(n or "").strip()}
    rows = [r for r in identities(sid)
            if _norm(r.get("name")) in wanted or _norm(r.get("display", "")) in wanted]
    rows.sort(key=lambda r: str(r.get("name") or ""))
    return rows


def _brief(rows: list[dict], limit: int = 8) -> str:
    out = []
    for r in rows[:limit]:
        addr = (f"{r['host']}:{r['port']}" if r.get("host") and r.get("port")
                else r.get("serial_port") or "地址未知")
        out.append(f"{r['name']}（{addr}）")
    return "、".join(out) + ("…" if len(rows) > limit else "")


def resolve_device(query: str, session: str = "") -> dict:
    """把任意设备写法解析成唯一身份。

    支持：设备名 / host:port / 裸 host / 端口号 / COM 口 / 由地址兜底生成的
    `192.168.1.1_2001` 形式，大小写不敏感。

    Returns:
        成功 `{"ok": True, "name": ..., "key": ..., "aliases": [...], "matched": ...}`
        失败 `{"ok": False, "reason": "empty"|"not_found"|"ambiguous",
                "candidates": [...], "message": "..."}`

    歧义（同名两台设备、或端口号命中多台）**不猜**，交回候选让调用方决定。
    """
    q = str(query or "").strip()
    if not q:
        return {"ok": False, "reason": "empty", "candidates": [],
                "message": "设备名不能为空"}
    qn = _norm(q)
    rows = identities(session)

    scored: list[tuple[int, dict, str]] = []
    for r in rows:
        aliases = [_norm(a) for a in r["aliases"]]
        name = _norm(r["name"])
        if qn == name:
            scored.append((100, r, "name"))
        elif qn == _norm(r["key"]) and r["key"]:
            scored.append((95, r, "key"))
        elif qn in aliases:
            scored.append((85, r, "alias"))
        elif qn == _norm(r.get("host")) and r.get("host"):
            scored.append((75, r, "host"))
        elif len(qn) >= 3 and not qn.isdigit() and any(
                qn in a or (len(a) >= 3 and a in qn) for a in aliases if a):
            scored.append((40, r, "fuzzy"))

    if not scored:
        near = [r for r in rows if qn in _norm(r["name"]) or _norm(r["name"]) in qn]
        msg = f"没有找到设备「{q}」。"
        if rows:
            msg += f"当前可查询的设备：{_brief(near or rows)}。"
            msg += "也可以直接用「IP:端口」查询；若在别的对话里，用 list_session_skills 查看分布。"
        return {"ok": False, "reason": "not_found", "candidates": [],
                "message": msg}

    best = max(s for s, _, _ in scored)
    top = [(r, why) for s, r, why in scored if s == best]
    uniq: dict[tuple[str, str], tuple[dict, str]] = {}
    for r, why in top:
        uniq.setdefault((r["key"], _norm(r["name"])), (r, why))
    if len(uniq) > 1:
        cands = [{"name": r["name"], "key": r["key"], "host": r["host"],
                  "port": r["port"], "serial_port": r["serial_port"]}
                 for r, _ in uniq.values()]
        return {"ok": False, "reason": "ambiguous", "candidates": cands,
                "message": (f"设备「{q}」匹配到 {len(cands)} 台不同的设备，拒绝猜测。"
                            f"请改用更精确的名字或地址：{_brief([r for r, _ in uniq.values()])}。")}

    r, why = next(iter(uniq.values()))
    return {"ok": True, "name": r["name"], "key": r["key"], "matched": why,
            "transport": r.get("transport", ""), "host": r.get("host", ""),
            "port": r.get("port", 0), "serial_port": r.get("serial_port", ""),
            "aliases": r["aliases"], "sources": sorted(r["sources"])}


# ---------------------------------------------------------------- 清单合并

def _inventory_devices() -> list[dict]:
    data = _read_json(INVENTORY_PATH, {})
    host = data.get("host", "")
    out = []
    for d in data.get("devices", []):
        out.append({
            "key": _device_key("telnet", host, int(d.get("port", 0))),
            "name": d.get("name", ""),
            "transport": "telnet",
            "host": host,
            "port": int(d.get("port", 0)),
            "vendor": d.get("vendor", ""),
            "model": d.get("model", ""),
            "type": d.get("type", ""),
            "manual": d.get("manual", ""),
            "source": "inventory",
        })
    return out


def _display_name(entry: dict) -> str:
    for k in ("name", "host"):
        v = entry.get(k)
        if v:
            if k == "host":
                return f"{v}:{entry.get('port', '')}" if entry.get("port") else v
            return v
    if entry.get("serial_port"):
        return entry["serial_port"]
    return entry.get("key", "未知设备")


def list_devices() -> list[dict]:
    """合并清单 = 种子清单 ∪ 访问记录（同 key 时以种子清单的元数据为准）。

    返回字段：key / name / transport / host / port / serial_port / vendor /
              model / type / manual / source / last_seen / access_count
    """
    accesses = _read_json(ACCESS_PATH, {"devices": {}}).get("devices", {})

    merged: dict[str, dict] = {}
    for d in _inventory_devices():
        merged[d["key"]] = {**d, "serial_port": "",
                            "last_seen": "", "access_count": 0}

    for key, a in accesses.items():
        if key in merged:
            merged[key]["last_seen"] = a.get("last_seen", "")
            merged[key]["access_count"] = int(a.get("count", 0))
            continue
        entry = {"key": key,
                 "transport": a.get("transport", "telnet"),
                 "host": a.get("host", ""),
                 "port": int(a.get("port", 0) or 0),
                 "serial_port": a.get("serial_port", ""),
                 "vendor": "", "model": "", "type": "", "manual": "",
                 "source": "access",
                 "last_seen": a.get("last_seen", ""),
                 "access_count": int(a.get("count", 0))}
        entry["name"] = a.get("name") or _display_name(entry)
        merged[key] = entry

    # 清单在前、访问记录在后；各自按名字排序
    items = list(merged.values())
    items.sort(key=lambda d: (d["source"] != "inventory", d.get("name", "")))
    return items


# ---------------------------------------------------------------- 在线探测

def _probe_one(dev: dict) -> dict:
    out = {**dev, "online": False, "detail": "", "elapsed": 0.0}
    try:
        if dev["transport"] == "serial":
            from core.device_conn import list_serial_ports
            t0 = time.time()
            ports = {p["device"] for p in list_serial_ports()}
            out["elapsed"] = round(time.time() - t0, 2)
            ok = dev.get("serial_port", "") in ports
            out["online"] = ok
            out["detail"] = "串口在线" if ok else "串口未枚举到（未插入或被占用）"
        else:
            from core.device_conn import probe_tcp
            r = probe_tcp(dev["host"], dev["port"], timeout=PROBE_TIMEOUT)
            out["elapsed"] = r.get("elapsed", 0.0)
            out["online"] = bool(r.get("ok"))
            out["detail"] = (f"TCP 可达（{r.get('elapsed')}s）" if r.get("ok")
                             else str(r.get("error", "不可达"))[:80])
    except Exception as e:
        out["detail"] = f"{type(e).__name__}: {e}"[:80]
    return out


def probe_all(devices: list[dict] | None = None) -> list[dict]:
    """并发探测全部设备的在线状态（只读，不下发任何命令）"""
    devs = devices if devices is not None else list_devices()
    if not devs:
        return []
    with ThreadPoolExecutor(max_workers=min(PROBE_WORKERS, len(devs))) as pool:
        return list(pool.map(_probe_one, devs))


def summary(results: list[dict]) -> str:
    online = sum(1 for r in results if r.get("online"))
    return f"共 {len(results)} 台 · 在线 {online} · 离线 {len(results) - online}"
