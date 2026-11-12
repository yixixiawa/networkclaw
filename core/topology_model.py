"""拓扑图数据模型：把「泛洪发现快照 + 设备注册表」合成 GUI 拓扑视图所需的节点/边。

数据来源与优先级（型号识别）：
1. 快照 results（泛洪时从设备回显解析的 sysname / model，最准——display version 原文）
2. 设备注册表 list_devices() 的 model（种子清单维护的）
3. 都没有 → 空，由 _infer_kind 从 sysname 前缀/拓扑角色推断大类，model 显示「未知」

快照缺失时降级：仅用注册表出节点（无连线），不报错——拓扑图是可视入口，
不能因为一次泛洪没跑过就整页空白。
"""
from __future__ import annotations

import json
import re

from core.paths import BASE_DIR

SNAPSHOT_PATH = BASE_DIR / "data" / "topology_discovered.json"


def session_snapshot_path(sid: str):
    """某会话自己的拓扑快照（discover_topology 在会话内落盘的副本）。"""
    from core.session_skills import session_dir

    return session_dir(sid or None) / "topology_discovered.json"


def _norm(s) -> str:
    """统一比较用的归一化：去空白 + 小写（与 device_registry._norm 同义）"""
    return str(s or "").strip().lower()


def _session_device_names(session: str) -> set[str]:
    """本会话出现过的设备目录名（有手册或有命令历史的）。"""
    try:
        from core import device_manual

        names = {m["name"] for m in device_manual.list_manuals(session)}
        names |= set(device_manual.history_only_devices(session))
        return names
    except Exception:  # noqa: BLE001
        return set()


def _session_match_set(session: str) -> set[str]:
    """本会话设备的全部可匹配标识（名字/别名/host:port），归一化小写。

    快照节点名是 sysname，会话目录名是绑定名，两者通常一致但不保证——
    所以把注册表行里的别名、地址一并纳入匹配集。
    """
    out = {_norm(n) for n in _session_device_names(session)}
    try:
        from core.device_registry import session_devices

        for r in session_devices(session):
            for a in r.get("aliases", ()):
                if str(a or "").strip():
                    out.add(_norm(a))
            if r.get("host"):
                out.add(_norm(r["host"]))
                if r.get("port"):
                    out.add(_norm(f"{r['host']}:{r['port']}"))
    except Exception:  # noqa: BLE001
        pass
    return out


def _registry_identities(session: str = "") -> list[dict]:
    """读设备注册表（失败返回空，拓扑不能因注册表故障整页崩掉）。"""
    try:
        from core.device_registry import identities

        return identities(session)
    except Exception:  # noqa: BLE001
        return []


def _infer_kind(sysname: str, role: str) -> str:
    """没有型号时的兜底分类（router/switch/firewall/unknown）。"""
    s = (sysname or "").upper()
    if s.startswith("FW") or "防火墙" in (role or ""):
        return "firewall"
    if s.startswith("SW") or s.startswith("LSW") or "接入" in (role or "") \
            or "核心" in (role or ""):
        return "switch"
    if s.startswith(("AR", "R")) and re.search(r"\d", s) or "出口" in (role or ""):
        return "router"
    return "unknown"


_SPEC = "（推测）"           # 推断出的型号统一带这个后缀，和原文解析的区分开


def _infer_model(result: dict, kind: str) -> str:
    """快照解析不出型号时，按回显特征推断。

    背景：eNSP 部分镜像的 `display version` 是模板横幅
    `Version 5.110 (eNSP V100R001C00)`，里面没有型号字样，parse_model 抓不到。
    只做高置信推断，全部带（推测）后缀——宁可少说，不编造型号：
    - 横幅含 `VRP WVSP`：USG 防火墙镜像独有分支 → USG6000V（eNSP 唯一防火墙）
    - 模板横幅 + GE 口交换机 → S5700 系列；ETH 口 → S3700 系列
    - 模板横幅 + 串口路由器 → AR 系列
    - 登录失败的设备不给型号，标「未知（登录失败）」
    """
    raw = result.get("raw") or {}
    if not result.get("ok", True):
        return "未知（登录失败）"
    banner = f"{raw.get('identity', '')} {result.get('version', '')}"
    if not banner.strip():
        return ""
    if "WVSP" in banner:
        return f"USG6000V{_SPEC}"
    if "(eNSP" not in banner:
        return ""
    ifs = raw.get("interfaces", "") or ""
    if kind == "switch":
        if re.search(r"\bGE\d|\bGigabitEthernet", ifs):
            return f"S5700 系列{_SPEC}"
        if re.search(r"\bETH?\d|\bEthernet", ifs):
            return f"S3700 系列{_SPEC}"
        return f"S 系列{_SPEC}"
    if kind == "router" and "Serial" in ifs:
        return f"AR 系列{_SPEC}"
    return ""


def classify(model: str, sysname: str = "", role: str = "") -> str:
    """设备大类：先按型号画像，再按 sysname/角色兜底。"""
    if model:
        try:
            from knowledge.device_profiles import device_kind

            k = device_kind(model)
            if k:
                return k
        except Exception:  # noqa: BLE001  画像缺失不影响绘图
            pass
    return _infer_kind(sysname, role)


def load_topology_model(snapshot_path=None, session: str = "",
                        registry: list[dict] | None = None,
                        session_devices: list[str] | None = None) -> dict:
    """合成拓扑视图数据。返回 {ok, nodes, edges, generated, error}。

    node: {key, name, model, kind, role, level, host, port, version}
    edge: {a, b, a_if, b_if, evidence, confidence}
    key 是 host:port（快照的稳定标识）；name 是给人看的（sysname 优先）。
    registry 参数用于测试注入；缺省读设备注册表。

    会话隔离（session 非空时生效）：
    - 快照优先读 `session/<sid>/topology_discovered.json`（discover_topology
      在会话内落盘的副本），没有再用全局快照；
    - 节点按**本会话设备**过滤（session/<sid>/skill/ 里有手册或命令历史的，
      名字/别名/地址任一命中即保留），边只保留两端都留下的——
      保证一个会话只看到自己拓扑，别的会话/历史残留不混进来；
    - session_devices 参数用于测试注入（覆盖目录扫描）。
    """
    path = snapshot_path
    used_session_snapshot = False
    if path is None and session:
        sp = session_snapshot_path(session)
        if sp.exists():
            path = sp
            used_session_snapshot = True
    path = path or SNAPSHOT_PATH
    snap: dict = {}
    if path and path.exists():
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001  快照坏了按没有处理，注册表兜底
            snap = {}
            err = f"快照解析失败：{type(e).__name__}: {e}"
        else:
            err = ""
    else:
        err = "" if path is None else "快照不存在（先跑一次拓扑发现）"

    results = {r.get("name"): r for r in snap.get("results", []) if r.get("name")}
    roles: dict = snap.get("roles") or {}
    levels: dict = snap.get("levels") or {}

    # 注册表：key(host:port) → 展示名兜底 + 串口设备补充进来
    registry = registry if registry is not None else _registry_identities(session)
    reg_by_key: dict[str, dict] = {}
    for it in registry or []:
        key = it.get("key") or ""
        if it.get("host"):
            key = f"{it['host']}:{it['port']}"
        reg_by_key[key] = it

    # 快照有效时只补注册表里的**串口**设备：Telnet 台账（device_access.json）
    # 记的是历史上连过的所有设备，跨实验会残留——全部并进来会出现一批
    # 无连线的幽灵节点（曾把另一套 10.0.0.x 实验的 25 台混进当前拓扑）。
    # 快照缺失/为空时才整体降级为注册表清单（无连线）。
    snap_devices = list(snap.get("devices") or [])
    if snap_devices:
        extra = [k for k, it in reg_by_key.items()
                 if (it.get("transport") or "") == "serial"]
    else:
        extra = list(reg_by_key.keys())
    node_keys: list[str] = list(dict.fromkeys(snap_devices + extra))

    nodes: list[dict] = []
    name_of: dict[str, str] = {}
    for key in node_keys:
        r = results.get(key) or {}
        reg = reg_by_key.get(key) or {}
        sysname = (r.get("sysname") or "").strip()
        model = (r.get("model") or "").strip()
        name = sysname or reg.get("display") or key
        role = roles.get(key, "")
        level = int(levels.get(key, 99))
        kind = classify(model, sysname, role)
        if kind == "unknown":
            # VRP 体系里带 Serial 口的只有路由器（交换机/防火墙没有串口板）——
            # eNSP 模拟终端常用路由器镜像 + 串口，据此归类才能套 AR 系列推断
            if "Serial" in ((r.get("raw") or {}).get("interfaces", "") or ""):
                kind = "router"
        if not model:
            model = (reg.get("model") or "").strip()
        if not model:
            # 注册表也没有：按快照回显特征做高置信推断（USG6000V 等，带（推测））
            model = _infer_model(r, kind)
        # host:port 形如 192.168.183.137:2001；串口是 serial:COM3 / COM3-serial，
        # 都不是「数字端口」结构，统一当非 IP 键处理
        host, port = key, 0
        if key.count(":") == 1:
            h, _, p = key.partition(":")
            if p.isdigit():
                host, port = h, int(p)
        nodes.append({
            "key": key, "name": name, "model": model or "未知型号",
            "kind": kind, "role": role or "未分类", "level": level,
            "host": host, "port": port,
            "version": (r.get("version") or "").strip(),
        })
        name_of[key] = name

    # ---- 会话过滤：只留本会话的设备（session 为空 = 不过滤，保持旧行为）----
    # 会话自己的快照（discover_topology 在本会话落盘的副本）内容天然属于本会话，
    # 不再按 skill 目录过滤；只有回退到全局快照时才需要按会话设备筛。
    filtered = 0
    if session and not used_session_snapshot:
        allowed = ({_norm(x) for x in (session_devices or [])}
                   if session_devices is not None else _session_match_set(session))
        kept = []
        for n in nodes:
            hit = (_norm(n["name"]) in allowed or _norm(n["key"]) in allowed
                   or (n["host"] and _norm(n["host"]) in allowed)
                   or (n["port"] and _norm(f"{n['host']}:{n['port']}") in allowed))
            if hit:
                kept.append(n)
        filtered = len(nodes) - len(kept)
        nodes = kept
        name_of = {n["key"]: n["name"] for n in nodes}

    edges = []
    for lk in snap.get("links") or []:
        a, b = lk.get("a_device"), lk.get("b_device")
        if a not in name_of or b not in name_of:
            continue  # 端点不在节点集里（旧快照残留/被会话过滤掉），画出来会悬空
        edges.append({
            "a": a, "b": b,
            "a_if": lk.get("a_interface", ""), "b_if": lk.get("b_interface", ""),
            "evidence": lk.get("evidence", ""), "confidence": lk.get("confidence", ""),
        })

    out = {"ok": bool(nodes), "nodes": nodes, "edges": edges,
           "generated": snap.get("generated", ""), "error": err,
           "session": session}
    if filtered:
        out["filtered"] = filtered
    if session and not nodes and not out["error"]:
        # 快照为空或全被会话过滤掉：给出下一步指引，别让人以为拓扑坏了
        out["error"] = ("本会话还没有拓扑数据：拓扑只显示当前会话的设备"
                        "（先让助手连接/建档设备，或在本会话运行拓扑发现）")
    return out
