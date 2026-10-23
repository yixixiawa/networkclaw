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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from core.paths import BASE_DIR

INVENTORY_PATH = BASE_DIR / "data" / "device_inventory.json"
ACCESS_PATH = BASE_DIR / "data" / "device_access.json"

_LOCK = threading.Lock()
PROBE_TIMEOUT = 2.0        # 单设备 TCP 探测超时（秒）
PROBE_WORKERS = 16         # 并发探测线程数


# ---------------------------------------------------------------- 读写

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
        with _LOCK:
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


def bind_name(transport: str, name: str, host: str = "", port: int = 0,
              serial_port: str = "") -> None:
    """把设备名绑定到某个地址（模型为该设备建档时调用）。

    绑定后，后续该地址的命令历史会自动归到这个名字的文件里，
    清单展示也用它代替裸地址。任何失败都静默。
    """
    try:
        name = (name or "").strip()
        if not name:
            return
        with _LOCK:
            data = _read_json(ACCESS_PATH, {"devices": {}})
            devices: dict = data.setdefault("devices", {})
            key = _device_key(transport, host, port, serial_port)
            entry = devices.get(key) or {}
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
    except Exception:
        pass


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
        return (entry.get("name") or sp or "unknown-serial").strip()

    accesses = _read_json(ACCESS_PATH, {"devices": {}}).get("devices", {})
    entry = accesses.get(_device_key("telnet", host, port)) or {}
    if entry.get("name"):
        return str(entry["name"]).strip()
    inventories = _inventory_devices()
    for d in inventories:
        if d["host"] == host and int(d["port"]) == int(port):
            return d["name"]
    return f"{host}_{port}" if port else (host or "unknown-device")


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
