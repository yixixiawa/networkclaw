"""拓扑泛洪发现：对每台设备"泛洪"只读探测命令，自动推导上下级关系与拓扑图。

为什么需要它：
    维护 `data/device_inventory.json` 里的 `topology_notes` 是手写的，
    设备一多、链路一改就过期（而且写错了没人发现）。
    设备自己其实"知道"邻居是谁——LLDP 邻居表、ARP 表、MAC 地址表都是现成的证据，
    只要逐台把这几张表读出来（**全是 display 类只读命令**），
    就能把「谁连着谁」这件事从人工记录变成实测事实，并顺带推出层级（上下级）。

核心思路（三级证据，越靠前越可靠）：
    1. LLDP 邻居表  `display lldp neighbor brief`
       最硬的证据：直接给出「本端口 → 邻居设备名 + 邻居口」。
       但要求对端也开了 LLDP，且 show 的是**设备名**（sysname）。
    2. MAC 地址表 + 桥接域推导  `display mac-address`
       交换机之间没跑 LLDP 时，可以用「同一个 MAC 在哪些口的后面」反推共享网段，
       但精度差（可能把一台机器后面的整片网络算成一个段），仅作为补充。
    3. ARP 表  `display arp`
       给「三层邻居」补 IP 与网段信息，用于标注而不是连线。

层级（上下级）怎么定：
    用**有向的 LLDP 邻居关系**做 BFS：以「没有上行邻居的设备」为根
    （通常是核心/出口，或者干脆是入参指定的 `roots`），未被指向的一端是下级。
    若图里有环（真实网络里有冗余链路很正常），BFS 会记录 `loop_edges`，
    不会因此崩掉或产生死循环。

安全：
    本模块只下发 `display` / `show` 开头的只读命令，全部命中 command_guard 的
    `allow` 级；解析器不产生任何配置类命令。默认也只读，不写回任何清单文件，
    需要落盘时显式调用 `save_snapshot()`。
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path

from core.paths import BASE_DIR

# 泛洪用的只读命令（全部 display/show，命中 command_guard 的 allow 级）
# 顺序有讲究：先拿身份，再拿邻居，最后兜底
FLOOD_COMMANDS: dict[str, str] = {
    "identity": "display version",
    "sysname": "display current-configuration | include sysname",
    "lldp": "display lldp neighbor brief",
    "lldp_verbose": "display lldp neighbor",
    "arp": "display arp",
    "mac": "display mac-address",
    "interfaces": "display ip interface brief",
    # 思科兼容（H3C/Cisco 设备）
    "cdp": "show cdp neighbors detail",
    "arp_cisco": "show ip arp",
}

SNAPSHOT_PATH = BASE_DIR / "data" / "topology_discovered.json"

DEFAULT_WORKERS = 4
DEFAULT_TIMEOUT = 25.0

# 设备名归一化：去掉 eNSP 常见后缀/大小写差异，避免 "SW1" 与 "<SW1>" 对不上
_NAME_CLEAN = re.compile(r"[<>\[\]\s]")


# ---------------------------------------------------------------- 数据结构

@dataclass
class Port:
    """一个已发现的物理/逻辑端口（作为连线端点）。"""
    device: str
    interface: str
    neighbor_device: str = ""
    neighbor_interface: str = ""


@dataclass
class DeviceResult:
    """单台设备的泛洪结果。"""
    name: str = ""
    host: str = ""
    port: int = 0
    ok: bool = False
    error: str = ""
    elapsed: float = 0.0
    sysname: str = ""
    model: str = ""
    version: str = ""
    # 原始回显（截断保存，便于人工核对解析是否正确）
    raw: dict[str, str] = field(default_factory=dict)


@dataclass
class Link:
    """一条已发现的链路（无向，但保留发现方向用于层级推导）。"""
    a_device: str
    a_interface: str
    b_device: str
    b_interface: str
    evidence: str = "lldp"          # lldp / cdp / mac
    confidence: str = "high"        # high（LLDP 明确）/ medium（MAC 推导）
    # 发现方向：src 是被探测设备（下级候选），dst 是它看到的邻居（上级候选）
    src: str = ""
    dst: str = ""

    @property
    def key(self) -> tuple:
        """端点对归一化后的去重键（(A口, B口) 与 (B口, A口) 视为同一条）。"""
        e1 = (self.a_device, self.a_interface)
        e2 = (self.b_device, self.b_interface)
        return tuple(sorted([e1, e2]))


@dataclass
class Topology:
    """完整拓扑：设备 + 链路 + 层级 + 诊断信息。"""
    devices: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    levels: dict[str, int] = field(default_factory=dict)
    parents: dict[str, str] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    loop_edges: list[tuple[str, str]] = field(default_factory=list)
    results: list[DeviceResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    generated: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------------------------------------------------------------- 回显解析

def clean_name(text: str) -> str:
    """归一化设备名：去尖括号/方括号/空白，统一大写比较用。"""
    return _NAME_CLEAN.sub("", str(text or "")).strip()


# 命令报错/提示行：任何把它当表格数据解析的尝试都会产出假邻居/假链路
_ERROR_LINE_RE = re.compile(
    r"^(Error|Info|Warning|Note|Prompt)\b[:：]?|"
    r"^%|"
    r"Unrecognized command|Wrong parameter|ambiguous command|"
    r"incomplete command|too many parameters|is not enabled|"
    r"^请|^错误|^提示",
    re.I,
)


def is_error_line(line: str) -> bool:
    """判断一行回显是不是命令报错/提示（LLDP 未开、命令拼错等）。"""
    return bool(_ERROR_LINE_RE.search(str(line or "")))


# 华为/思科常见接口名前缀（用于把「长得像接口」的列与错误文本碎片区分开）
_IFACE_PREFIX_RE = re.compile(
    r"^(?:GE|XGE|10GE|25GE|40GE|100GE|200GE|400GE|Eth-?Trunk|Ethernet|Gi|Fa|Te|"
    r"Twe|Hu|HundredGigE|Se|Serial|POS|Vlanif|Vlan|LoopBack|Loopback|Tunnel|"
    r"MEth|NVE|Vbdif|Cellular|mgmt|Management)\d*",
    re.I,
)


def looks_like_interface(token: str) -> bool:
    """token 是否像接口名（GE0/0/1、Eth-Trunk1、GigabitEthernet0/0/1…）

    必须前缀命中且含数字——否则 "Huawei" 这类词也会以 `Hu` 开头混进来。
    """
    t = str(token or "").strip()
    return bool(t) and bool(_IFACE_PREFIX_RE.match(t)) and bool(re.search(r"\d", t))


def parse_sysname(text: str) -> str:
    """从 `display current-configuration | include sysname` 回显取设备名。"""
    for line in str(text or "").splitlines():
        line = line.strip()
        m = re.match(r"^sysname\s+(\S+)", line, re.I)
        if m:
            return clean_name(m.group(1))
    return ""


def parse_model(text: str) -> str:
    """从 `display version` 回显取型号（Huawei 的 `Quidway S5700-28C-HI` 等）。"""
    for line in str(text or "").splitlines():
        line = line.strip()
        # 华为：`Huawei Versatile Routing Platform Software ... ` + `Quidway S5700...`
        m = re.search(r"\b(?:Quidway|Huawei)\s+([A-Z]{1,3}\d{3,5}[A-Z0-9\-/]*)", line)
        if m:
            return m.group(1)
        # 思科：`cisco WS-C2960-24TT-L (PowerPC405) processor`
        m = re.match(r"^cisco\s+(\S+)", line, re.I)
        if m:
            return m.group(1)
    return ""


def parse_version(text: str) -> str:
    """取 VRP/IOS 版本号，纯展示用。"""
    m = re.search(r"Version\s+([\w.()]+)", str(text or ""))
    return m.group(1) if m else ""


def normalize_interface(name: str, device: str = "", model: str = "") -> str:
    """接口名归一化：去掉空格与常见前缀，统一大写。

    eNSP 里 LLDP 邻居表可能写成 `GigabitEthernet0/0/1`、`GE0/0/1`、`Gi0/1`，
    统一成短名 `GE0/0/1` 才能和 inventory / 真机回显对上。
    """
    s = re.sub(r"\s+", "", str(name or "")).strip()
    if not s:
        return ""
    table = [
        # 聚合口必须排在 Ethernet(Eth) 之前——否则 "Eth-Trunk1" 会被 ETH 规则吃掉
        (r"^(Bridge-Aggregation|BAGG|Port-channel|Po)(?![a-z])", "Eth-Trunk"),
        (r"^(Eth-Trunk|Eth-trunk|ETH-TRUNK)", "Eth-Trunk"),
        (r"^(GigabitEthernet|GE|Gi)(?![a-z])", "GE"),
        (r"^(FastEthernet|Fa|FE|Fas)", "FE"),
        (r"^(TenGigabitEthernet|XGigabitEthernet|10GE|XGE|Te|TenGigE)", "XGE"),
        (r"^(40GE|FortyGigE|FGE)", "40GE"),
        (r"^(100GE|HundredGigE|HGE)", "100GE"),
        (r"^(Ethernet|Eth|ET)", "ETH"),
        (r"^(Vlanif|Vlan-interface|VLAN|Vl)", "Vlanif"),
        (r"^(LoopBack|Loopback|Loop|Lo)", "LoopBack"),
        (r"^(Tunnel|Tun)", "Tunnel"),
        (r"^(MEth|ME)", "MEth"),
        (r"^(NULL|Nul)", "NULL"),
    ]
    for pat, short in table:
        if re.match(pat, s, re.I):
            rest = re.sub(pat, "", s, flags=re.I)
            # 只保留数字/点/斜杠，避免把表头残留带进来
            rest = re.sub(r"[^\d/\.:]", "", rest)
            return f"{short}{rest}".upper()
    return s.upper()


def _norm_mac(mac: str) -> str:
    """华为 `00e0-fc12-3456` / 思科 `00e0.fc12.3456` → 统一的 12 位十六进制。"""
    return re.sub(r"[-:.\s]", "", str(mac or "")).lower()


def parse_lldp_brief(text: str) -> list[dict]:
    """解析 `display lldp neighbor brief`（华为）表格。

    典型回显（列：Local Intf / Neighbor Dev / Neighbor Intf / Exptime）::

        Local Intf          Neighbor Dev                  Neighbor Intf           Exptime
        -------------------------------------------------------------------------------
        GE0/0/1             SW2                           GE0/0/1                 102
        GE0/0/2             SW2                           GE0/0/2                 102

    返回 [{"local": "GE0/0/1", "device": "SW2", "remote": "GE0/0/1"}, ...]
    """
    out: list[dict] = []
    for line in str(text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("-"):
            continue
        # 报错行必须整体跳过：LLDP 未开时设备回显 `Error: Global LLDP is not enabled.`，
        # 按 2+ 空格切不开、退化为单空格切分后会被当成
        # local="Error:" dev="Global" remote="LLDP" 的假邻居（2026-10-23 实测踩坑，
        # 生成了整页 "ERROR: ↔ Global:LLDP" 垃圾边）。
        if is_error_line(s):
            continue
        if re.match(r"^(Local\s+Intf|LocalInterface|Local\s+Interface)", s, re.I):
            continue
        parts = re.split(r"\s{2,}", s)
        if len(parts) < 3:
            parts = s.split()
        if len(parts) < 3:
            continue
        local, dev, remote = parts[0], parts[1], parts[2]
        if not re.match(r"^[A-Za-z]", local):
            continue
        # 本地列必须是「长得像接口」的 token，进一步挡住错误文本碎片
        if not looks_like_interface(local):
            continue
        # 排除表头残留
        if clean_name(dev).lower() in ("neighbordev", "neighbor"):
            continue
        out.append({
            "local": normalize_interface(local),
            "device": clean_name(dev),
            "remote": normalize_interface(remote),
        })
    return out


def parse_lldp_verbose(text: str) -> list[dict]:
    """解析 `display lldp neighbor`（逐口详细）与思科 `show cdp neighbors detail`。

    华为逐口形态::

        GE0/0/1 has 1 neighbor(s):
        Neighbor index                   :1
            Chassis type                 :MAC address
            ...
            System name                  : SW2
        Port ID type                     :Interface name
        Port ID                          : GigabitEthernet0/0/1

    思科形态::

        Device ID: SW2
        Entry address(es):
          IP address: 10.0.0.2
        Interface: GigabitEthernet0/0/1,  Port ID (outgoing port): GigabitEthernet0/0/1
    """
    out: list[dict] = []
    if not text:
        return out
    current_local = ""
    pending_dev = ""
    for raw_line in str(text).splitlines():
        line = raw_line.rstrip()
        s = line.strip()
        if is_error_line(s):
            continue

        # 华为：`GE0/0/1 has 1 neighbor(s)`
        m = re.match(r"^([A-Za-z][\w/\-\.]*)\s+has\s+\d+\s+neighbor", s, re.I)
        if m:
            current_local = normalize_interface(m.group(1))
            pending_dev = ""
            continue

        # 华为：System name : SW2    / 思科：Device ID: SW2
        m = re.match(r"^(?:System\s+name|System\s+Name|Device\s+ID)\s*[:\s]\s*(\S+)", s, re.I)
        if m:
            pending_dev = clean_name(m.group(1))
            continue

        # 华为：Port ID  : GigabitEthernet0/0/1   （跳过 Port ID type 行）
        m = re.match(r"^Port\s+ID\s*:\s*(\S+)", s, re.I)
        if m and pending_dev:
            remote = normalize_interface(m.group(1))
            if current_local:
                out.append({"local": current_local,
                            "device": pending_dev,
                            "remote": remote})
            pending_dev = ""
            continue

        # 思科：Interface: GigabitEthernet0/0/1,  Port ID (outgoing port): Gi0/1
        m = re.match(r"^Interface\s*:\s*([\w/\-\.]+)\s*,\s*Port\s+ID[^:]*:\s*(\S+)", s, re.I)
        if m:
            out.append({"local": normalize_interface(m.group(1)),
                        "device": pending_dev or current_local or "?",
                        "remote": normalize_interface(m.group(2))})
            continue

    # 思科形态里 Device ID 出现在 Interface 之前，上面已用 pending_dev 承接
    return out


def parse_arp(text: str) -> list[dict]:
    """解析 `display arp`（华为）与 `show ip arp`（思科）。

    华为::

        IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE        INTERFACE   VPN-INSTANCE
        10.0.0.1        00e0-fc12-3456            I -S      GE0/0/1
    """
    out: list[dict] = []
    for line in str(text or "").splitlines():
        s = line.strip()
        m = re.match(
            r"^(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{4}[-:.]?[0-9a-fA-F]{4}[-:.]?[0-9a-fA-F]{4})\s+\S*\s*(.*)$",
            s)
        if not m:
            continue
        ip, mac, rest = m.group(1), m.group(2), m.group(3)
        iface = ""
        # 接口一般是剩下的字段里第一个含字母的 token
        for tok in rest.split():
            if re.match(r"^(GE|FE|Eth|XGE|Vlanif|LoopBack|MEth)", tok, re.I):
                iface = normalize_interface(tok)
                break
        out.append({"ip": ip, "mac": _norm_mac(mac), "interface": iface})
    return out


def parse_mac_table(text: str) -> list[dict]:
    """解析 `display mac-address`（华为）。

    华为::

        MAC Address       VLAN/VSI/BD    Learned-From         Type
        -------------------------------------------------------------------------
        00e0-fc12-3456    10/-/-         GE0/0/1              dynamic
    """
    out: list[dict] = []
    for line in str(text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("-"):
            continue
        m = re.match(
            r"^([0-9a-fA-F]{4}[-:.]?[0-9a-fA-F]{4}[-:.]?[0-9a-fA-F]{4})\s+(\S+)\s+(\S+)\s+(\S+)",
            s)
        if not m:
            continue
        mac = _norm_mac(m.group(1))
        vlan = m.group(2).split("/")[0]
        iface = normalize_interface(m.group(3))
        if not re.match(r"^(GE|FE|Eth|XGE|MEth|Vlanif)", iface):
            continue
        out.append({"mac": mac, "vlan": vlan, "interface": iface, "type": m.group(4)})
    return out


def parse_interfaces(text: str) -> list[dict]:
    """解析 `display ip interface brief`，取接口 IP 与状态。

    华为::

        Interface                         IP Address      Physical     Protocol
        GE0/0/1                           10.0.0.1        up           up
        GE0/0/2                           unassigned      down         down

    列数不固定（有的版本无 `Protocol` 列），所以只要求「接口名 + IP/unassigned」，
    后面的 up/down 有则取、无则留空。
    """
    out: list[dict] = []
    for line in str(text or "").splitlines():
        s = line.strip()
        m = re.match(r"^([A-Za-z][\w/\-\.]*)\s+(\d{1,3}(?:\.\d{1,3}){3}|unassigned)\b(.*)$",
                     s, re.I)
        if not m:
            continue
        iface = normalize_interface(m.group(1))
        rest = m.group(3).split()
        out.append({
            "interface": iface,
            "ip": m.group(2),
            "physical": rest[0] if rest else "",
            "protocol": rest[1] if len(rest) > 1 else "",
        })
    return out


def parse_identity(dev: str, raw: dict[str, str]) -> DeviceResult:
    """把一台设备的原始回显汇总成 DeviceResult（纯函数，便于测试）。"""
    sysname = parse_sysname(raw.get("sysname", "")) or parse_sysname(raw.get("identity", ""))
    ver_text = raw.get("identity", "")
    res = DeviceResult(
        name=dev,
        sysname=sysname,
        model=parse_model(ver_text),
        version=parse_version(ver_text),
        raw={k: v[:2000] for k, v in raw.items()},
    )
    if not res.sysname:
        m = re.search(r"<([^>]+)>", ver_text)
        if m:
            res.sysname = clean_name(m.group(1))
    return res


# ---------------------------------------------------------------- 泛洪执行

def _commands_for_vendor(vendor: str) -> dict[str, str]:
    """按厂商挑选命令集（华为/H3C 用 display，思科用 show）。"""
    v = (vendor or "").lower()
    if "cisco" in v:
        return {
            "identity": "show version",
            "sysname": "show running-config | include hostname",
            "cdp": "show cdp neighbors detail",
            "lldp_verbose": "show cdp neighbors detail",
            "arp": "show ip arp",
            "arp_cisco": "show ip arp",
            "mac": "show mac address-table",
            "interfaces": "show ip interface brief",
        }
    return dict(FLOOD_COMMANDS)


def flood_device(device: dict, timeout: float = DEFAULT_TIMEOUT,
                 commands: dict[str, str] | None = None,
                 session_factory=None) -> DeviceResult:
    """对单台设备泛洪只读探测命令，返回原始回显集合。

    `session_factory` 注入点：签名 (device, timeout) -> 已登录的会话对象，
    需要实现 `exec_command(cmd, timeout)` 与 `close()`。
    默认用 `core.device_conn.open_telnet`，测试时可传假设备。
    """
    name = device.get("name") or f"{device.get('host')}:{device.get('port')}"
    res = DeviceResult(name=name, host=device.get("host", ""),
                       port=int(device.get("port", 0) or 0))
    cmds = commands or _commands_for_vendor(device.get("vendor", ""))
    t0 = time.time()
    sess = None
    try:
        if session_factory is None:
            from core.device_conn import open_telnet
            sess = open_telnet(
                device.get("host", ""), int(device.get("port", 23) or 23),
                username=str(device.get("username", "") or ""),
                password=str(device.get("password", "") or ""),
                timeout=timeout)
        else:
            sess = session_factory(device, timeout)

        # 关分页，否则长表会卡在 ---- More ----
        try:
            sess.prepare(disable_paging=True)
        except Exception:
            pass

        for key, cmd in cmds.items():
            try:
                out = sess.exec_command(cmd, timeout=timeout)
            except Exception as e:
                out = f"<执行失败：{type(e).__name__}: {e}>"
            res.raw[key] = out or ""
        res.ok = True
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    finally:
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass
        res.elapsed = round(time.time() - t0, 2)

    ident = parse_identity(name, res.raw)
    res.sysname = ident.sysname or res.sysname
    res.model = ident.model
    res.version = ident.version
    return res


def flood_all(devices: list[dict], workers: int = DEFAULT_WORKERS,
              timeout: float = DEFAULT_TIMEOUT, progress=None) -> list[DeviceResult]:
    """并发泛洪所有设备（每台一条独立连接，互不干扰）。"""
    if not devices:
        return []
    out: list[DeviceResult] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(devices)))) as pool:
        futs = {pool.submit(flood_device, d, timeout): d for d in devices}
        for fut in as_completed(futs):
            d = futs[fut]
            try:
                r = fut.result()
            except Exception as e:      # 兜底：单台失败不影响整轮
                r = DeviceResult(name=d.get("name", "?"),
                                 host=d.get("host", ""),
                                 port=int(d.get("port", 0) or 0),
                                 error=f"{type(e).__name__}: {e}"[:200])
            out.append(r)
            if progress:
                try:
                    progress(r)
                except Exception:
                    pass
    order = {d.get("name", ""): i for i, d in enumerate(devices)}
    out.sort(key=lambda r: order.get(r.name, 999))
    return out


# ---------------------------------------------------------------- 拓扑推导

def _resolve_name(alias: str, known: dict[str, str]) -> str:
    """把 LLDP 里的邻居名解析成清单里的设备名（大小写/尖括号差异容忍）。"""
    c = clean_name(alias)
    if not c:
        return ""
    if c in known:
        return known[c]
    low = {k.lower(): v for k, v in known.items()}
    return low.get(c.lower(), c)


def build_topology(results: list[DeviceResult],
                   devices: list[dict] | None = None,
                   roots: list[str] | None = None) -> Topology:
    """从泛洪结果推导拓扑、层级与上下级关系。"""
    topo = Topology(generated=time.strftime("%Y-%m-%d %H:%M:%S"))

    # 别名表：sysname / 设备名 / 主机:端口 → 规范设备名
    known: dict[str, str] = {}
    for r in results:
        known[clean_name(r.name)] = clean_name(r.name)
        if r.sysname:
            known[clean_name(r.sysname)] = clean_name(r.name)
    for d in (devices or []):
        nm = clean_name(d.get("name", ""))
        if nm:
            known.setdefault(nm, nm)

    names = [clean_name(r.name) for r in results if clean_name(r.name)]
    for n in names:
        if n not in topo.devices:
            topo.devices.append(n)

    seen: set[tuple] = set()
    for r in results:
        src = clean_name(r.name)
        if not src:
            continue
        if not r.ok:
            topo.notes.append(f"{src}：探测失败（{r.error or '未知原因'}），无法参与拓扑推导")
            continue

        nbrs = parse_lldp_brief(r.raw.get("lldp", ""))
        if not nbrs:
            nbrs = parse_lldp_verbose(r.raw.get("lldp_verbose", ""))
        if not nbrs:
            nbrs = parse_lldp_verbose(r.raw.get("cdp", ""))
        if not nbrs:
            topo.notes.append(f"{src}：未读到 LLDP/CDP 邻居（对端可能未开启，或未标注 sysname）")

        for nb in nbrs:
            dst = _resolve_name(nb["device"], known)
            if not dst or dst == src:
                continue
            link = Link(a_device=src, a_interface=nb["local"],
                        b_device=dst, b_interface=nb["remote"],
                        evidence="lldp", confidence="high",
                        src=src, dst=dst)
            if link.key in seen:
                continue
            seen.add(link.key)
            topo.links.append(link)

    # ---- MAC 表补充（仅当两设备间还没有 LLDP 链路时，用共享 MAC 反推）
    if topo.links:
        have = {frozenset((l.a_device, l.b_device)) for l in topo.links}
    else:
        have = set()
    mac_owner: dict[tuple[str, str], str] = {}
    macs: dict[str, dict[str, list[str]]] = {}
    for r in results:
        src = clean_name(r.name)
        if not r.ok:
            continue
        for e in parse_mac_table(r.raw.get("mac", "")):
            macs.setdefault(src, {}).setdefault(e["mac"], []).append(e["interface"])
    for src, table in macs.items():
        for mac, ifaces in table.items():
            mac_owner[(src, mac)] = ifaces[0]
    for (d1, mac), i1 in mac_owner.items():
        for (d2, mac2), i2 in mac_owner.items():
            if d1 >= d2 or mac != mac2:
                continue
            if frozenset((d1, d2)) in have:
                continue
            have.add(frozenset((d1, d2)))
            topo.links.append(Link(a_device=d1, a_interface=i1,
                                   b_device=d2, b_interface=i2,
                                   evidence="mac", confidence="medium",
                                   src=d1, dst=d2))

    for r in results:
        src = clean_name(r.name)
        if not r.ok:
            continue
        for a in parse_arp(r.raw.get("arp", "")):
            if a["interface"]:
                topo.notes.append(
                    f"{src}：ARP {a['ip']} 在 {a['interface']}（三层邻居，用于标注网段）")

    if not topo.links:
        topo.notes.append("未发现任何链路：请确认设备已开启 LLDP（`lldp enable`）且对端 sysname 已设置")

    _assign_levels(topo, roots)
    _assign_roles(topo, devices, results)
    topo.results = results
    return topo


def _assign_levels(topo: Topology, roots: list[str] | None) -> None:
    """定层级 + 记冗余环。

    **为什么不能只用有向关系**：LLDP 是双向的——SW1 看到 SW2，SW2 也看到 SW1。
    若只按「A 看到 B ⇒ A 指向 B」建有向图，两点会互相指向，
    从任一点 BFS 都会立刻发现对方"已在 levels 里"，于是永远建不出父子关系。

    正确做法：
      1. 链路本身是**无向**的（谁连谁），用无向邻接表 BFS 生成**生成树**定层级；
      2. 层级只能来自"父节点"，父节点选择优先用 LLDP 方向信息
         （A 看到 B 且 B 没看到 A ⇒ B 更像上级；互为邻居时按度数/名称稳定裁决）；
      3. 生成树之外的边 = 冗余链路（真实的双上行/环），记录下来但不参与层级。
    """
    # 无向邻接表（连线关系），同时保留有向信息用于决定父子方向
    adj: dict[str, set[str]] = {d: set() for d in topo.devices}
    directed: dict[tuple[str, str], int] = {}
    for l in topo.links:
        a, b = l.a_device, l.b_device
        if a not in adj or b not in adj or a == b:
            continue
        adj[a].add(b)
        adj[b].add(a)
        # 记录发现方向：src -> dst 出现一次
        if l.src and l.dst:
            directed[(l.src, l.dst)] = directed.get((l.src, l.dst), 0) + 1

    # ---- 选根：用户指定 > 无任何 LLDP 指向（不在任何 directed 的 dst 里）
    if roots:
        start = [clean_name(r) for r in roots if clean_name(r) in adj]
    else:
        pointed = {dst for (_s, dst) in directed}
        start = [d for d in topo.devices if adj[d] and d not in pointed]
    if not start:
        # 全是互相指（对称拓扑）或空图：取度数最大的当根，保证稳定
        cand = [d for d in topo.devices if adj[d]] or list(topo.devices)
        start = [max(cand, key=lambda d: (len(adj[d]), d))] if cand else []

    levels: dict[str, int] = {}
    parents: dict[str, str] = {}
    visited_edges: set[frozenset] = set()
    queue: list[tuple[str, int]] = []
    pinned = set(start)          # 显式/推断出的根，绝不能被降级
    for s in start:
        levels[s] = 0
        queue.append((s, 0))

    def _prefer_parent(cur: str, candidate: str) -> bool:
        """判断 cur 是否更适合当 candidate 的父节点（越大越适合）。

        LLDP 方向是首要依据：若 cur 看到 candidate 而 candidate 没看到 cur，
        说明 cur 是 candidate 的上行端 → 让 cur 当父。
        已定级的根（pinned）永远优先当父，避免被对称邻居顶掉。
        """
        if candidate in pinned:
            return False
        if cur in pinned:
            return True
        cur_sees = directed.get((cur, candidate), 0)
        cand_sees = directed.get((candidate, cur), 0)
        if cur_sees and not cand_sees:
            return True
        if cand_sees and not cur_sees:
            return False
        # 对称（互为邻居）：度数小的当子（更靠边缘）
        return len(adj[cur]) >= len(adj[candidate])

    while queue:
        cur, lv = queue.pop(0)
        for nxt in sorted(adj[cur]):
            if nxt == cur:
                continue
            edge = frozenset((cur, nxt))
            if edge in visited_edges:
                continue
            if nxt not in levels:
                # 首次到达 → 生成树里的一条边，cur 是父
                if _prefer_parent(cur, nxt):
                    levels[nxt] = lv + 1
                    parents[nxt] = cur
                    visited_edges.add(edge)
                    queue.append((nxt, lv + 1))
                else:
                    # cur 其实更靠下，先把 nxt 当父（回边）
                    levels[cur] = lv + 1
                    parents[cur] = nxt
                    visited_edges.add(edge)
                    queue.append((cur, lv + 1))
            else:
                # 两端都已有层级 → 这条边是冗余链路（生成树之外）
                visited_edges.add(edge)
                if abs(levels[nxt] - lv) <= 1:
                    topo.loop_edges.append((cur, nxt) if levels[nxt] >= lv
                                           else (nxt, cur))

    for d in topo.devices:
        levels.setdefault(d, 0)
    topo.levels = levels
    topo.parents = parents
    # 去重环边（同一条边可能被两个方向各记一次）
    dedup: list[tuple[str, str]] = []
    seen = set()
    for a, b in topo.loop_edges:
        k = frozenset((a, b))
        if k not in seen:
            seen.add(k)
            dedup.append((a, b))
    topo.loop_edges = dedup
    if topo.loop_edges:
        topo.notes.append(
            f"发现 {len(topo.loop_edges)} 条冗余链路（等价路径）："
            + "、".join(f"{a}↔{b}" for a, b in topo.loop_edges[:6])
            + "——正常的冗余/聚合设计，不参与层级计算")


def _assign_roles(topo: Topology, devices: list[dict] | None,
                  results: list[DeviceResult]) -> None:
    """给设备打角色标签：core（核心/根）/ access（接入/叶子）/ transit（汇聚）。"""
    kinds = {clean_name(d.get("name", "")): (d.get("type", "") or "")
             for d in (devices or [])}
    for r in results:
        if r.model:
            kinds.setdefault(clean_name(r.name), "")
            if not kinds.get(clean_name(r.name)):
                m = r.model.upper()
                if m.startswith("AR") or m.startswith("NE") or m.startswith("USG"):
                    kinds[clean_name(r.name)] = "router"
                elif m.startswith("S") or m.startswith("LSW"):
                    kinds[clean_name(r.name)] = "switch"

    degree: dict[str, int] = {d: 0 for d in topo.devices}
    child_count: dict[str, int] = {d: 0 for d in topo.devices}
    for l in topo.links:
        for d in (l.a_device, l.b_device):
            if d in degree:
                degree[d] += 1
    for _child, parent in topo.parents.items():
        if parent in child_count:
            child_count[parent] += 1

    for d in topo.devices:
        lv = topo.levels.get(d, 0)
        deg = degree[d]
        kids = child_count[d]
        if deg == 0:
            topo.roles[d] = "孤立"
        elif lv == 0:
            # 根：别人都指向它。它下面挂了设备 = 核心；只挂 0~1 个 = 出口/终端
            topo.roles[d] = "核心 / 根" if kids >= 2 else "出口 / 根"
        elif kids >= 2:
            topo.roles[d] = "汇聚"
        elif kids == 1:
            topo.roles[d] = "中间设备"
        else:
            topo.roles[d] = "接入 / 叶子"


# ---------------------------------------------------------------- 渲染

KIND_ICON = {"router": "🛣", "switch": "🔀", "firewall": "🛡", "": "▢"}


def render_text(topo: Topology) -> str:
    """人类可读的拓扑报告（终端 / 聊天窗口都能看）。"""
    lines: list[str] = []
    lines.append("=" * 68)
    lines.append(f"拓扑泛洪发现结果（{topo.generated}）")
    lines.append("=" * 68)
    lines.append(f"设备 {len(topo.devices)} 台 · 链路 {len(topo.links)} 条 · "
                 f"层级 {max(topo.levels.values(), default=0) + 1} 层")

    lines.append("")
    lines.append("【设备清单（按层级）】")
    for d in sorted(topo.devices, key=lambda x: (topo.levels.get(x, 0), x)):
        lv = topo.levels.get(d, 0)
        parent = topo.parents.get(d, "")
        role = topo.roles.get(d, "")
        up = f" ↑{parent}" if parent else ""
        lines.append(f"  L{lv}  {d:<10} {role:<10}{up}")

    lines.append("")
    lines.append("【上下级关系】")
    if topo.parents:
        for child, parent in sorted(topo.parents.items()):
            lines.append(f"  {parent}  └─ {child}")
    else:
        lines.append("  （未推导出层级关系）")

    lines.append("")
    lines.append("【链路】")
    if topo.links:
        for l in topo.links:
            tag = "LLDP" if l.evidence == "lldp" else "MAC "
            conf = "确定" if l.confidence == "high" else "推测"
            lines.append(f"  [{tag}/{conf}] {l.a_device}:{l.a_interface}  ↔  "
                         f"{l.b_device}:{l.b_interface}")
    else:
        lines.append("  （未发现链路）")

    if topo.notes:
        lines.append("")
        lines.append("【诊断】")
        for n in topo.notes:
            lines.append(f"  · {n}")

    lines.append("")
    lines.append("【Mermaid 拓扑图】")
    lines.append(render_mermaid(topo))
    return "\n".join(lines)


def render_mermaid(topo: Topology, direction: str = "TD") -> str:
    """生成 Mermaid 图（可贴进 Markdown / 腾讯文档直接渲染）。"""
    out = [f"graph {direction}"]
    # 节点：带层级与角色
    for d in topo.devices:
        lv = topo.levels.get(d, 0)
        role = topo.roles.get(d, "")
        nid = re.sub(r"[^0-9A-Za-z_]", "_", d)
        label = f"{d}<br/>L{lv} {role}" if role else f"{d}<br/>L{lv}"
        out.append(f'    {nid}["{label}"]')
    # 边：带两端接口名
    for l in topo.links:
        a = re.sub(r"[^0-9A-Za-z_]", "_", l.a_device)
        b = re.sub(r"[^0-9A-Za-z_]", "_", l.b_device)
        lbl = f"{l.a_interface} ↔ {l.b_interface}"
        if l.confidence == "medium":
            out.append(f'    {a} -. "{lbl}（推测）" .- {b}')
        else:
            out.append(f'    {a} -- "{lbl}" --- {b}')
    # 冗余链路用虚线红边标出
    for a_dev, b_dev in topo.loop_edges:
        a = re.sub(r"[^0-9A-Za-z_]", "_", a_dev)
        b = re.sub(r"[^0-9A-Za-z_]", "_", b_dev)
        out.append(f'    {a} -. "冗余" .- {b}')
    return "\n".join(out)


def render_dot(topo: Topology) -> str:
    """Graphviz DOT 输出（需要更精细排版时用）。"""
    out = ["digraph topology {", '  rankdir=TB;',
           '  node [shape=box, style=rounded];']
    for d in topo.devices:
        lv = topo.levels.get(d, 0)
        role = topo.roles.get(d, "").replace("/", "\\/")
        out.append(f'  "{d}" [label="{d}\\nL{lv} {role}"];')
    for l in topo.links:
        style = "" if l.confidence == "high" else ", style=dashed"
        out.append(f'  "{l.a_device}" -> "{l.b_device}" '
                   f'[label="{l.a_interface} <-> {l.b_interface}"{style}];')
    out.append("}")
    return "\n".join(out)


def context_for_model(topo: Topology, max_chars: int = 1800) -> str:
    """压成给模型看的紧凑摘要（注入 prompt 用）。"""
    parts = [f"实测拓扑（{topo.generated}，LLDP/MAC 泛洪发现，非人工录入）："]
    parts.append("设备层级：" + "；".join(
        f"{d}=L{topo.levels.get(d, 0)}" for d in sorted(
            topo.devices, key=lambda x: topo.levels.get(x, 0))))
    if topo.links:
        parts.append("链路：" + "；".join(
            f"{l.a_device}:{l.a_interface}↔{l.b_device}:{l.b_interface}"
            + ("(推测)" if l.confidence == "medium" else "")
            for l in topo.links))
    if topo.parents:
        parts.append("上下级：" + "；".join(
            f"{c}→挂在→{p}" for c, p in sorted(topo.parents.items())))
    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（已截断）"
    return text


# ---------------------------------------------------------------- 落盘

def save_snapshot(topo: Topology, path: Path = SNAPSHOT_PATH) -> Path:
    """把发现的拓扑落盘（供下次启动直接复用，避免每次都泛洪）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = topo.to_dict()
    data["_说明"] = ("拓扑泛洪发现的实测结果（display lldp neighbor / display mac-address）。"
                     "由 core/topology_flood.py 生成，可被人工核对并覆盖。")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_snapshot(path: Path = SNAPSHOT_PATH) -> Topology | None:
    """读取上次的发现结果。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    topo = Topology(
        devices=list(data.get("devices", [])),
        levels=dict(data.get("levels", {})),
        parents=dict(data.get("parents", {})),
        roles=dict(data.get("roles", {})),
        loop_edges=[tuple(e) for e in data.get("loop_edges", [])],
        notes=list(data.get("notes", [])),
        generated=data.get("generated", ""),
    )
    for l in data.get("links", []):
        topo.links.append(Link(**{k: l.get(k, "") for k in
                                  ("a_device", "a_interface", "b_device", "b_interface",
                                   "evidence", "confidence", "src", "dst")}))
    return topo


def snapshot_age_min(path: Path = SNAPSHOT_PATH) -> float | None:
    import os
    try:
        return round((time.time() - os.path.getmtime(path)) / 60.0, 1)
    except Exception:
        return None


# ---------------------------------------------------------------- 编排

def discover(devices: list[dict] | None = None, roots: list[str] | None = None,
             workers: int = DEFAULT_WORKERS, timeout: float = DEFAULT_TIMEOUT,
             save: bool = False, session_factory=None, progress=None) -> Topology:
    """一步到位：泛洪 → 解析 → 推导 → 返回拓扑。"""
    if devices is None:
        from core.device_registry import list_devices
        devices = [d for d in list_devices() if d.get("transport") == "telnet"]
    results = flood_all(devices, workers=workers, timeout=timeout,
                        progress=progress) if session_factory is None else \
        _flood_seq(devices, timeout, session_factory, progress)
    topo = build_topology(results, devices=devices, roots=roots)
    if save:
        save_snapshot(topo)
    return topo


def _flood_seq(devices: list[dict], timeout: float, session_factory, progress):
    """串行版泛洪（注入 session_factory 时用，便于测试与避免并发假设备）。"""
    out: list[DeviceResult] = []
    for d in devices:
        r = flood_device(d, timeout=timeout, session_factory=session_factory)
        out.append(r)
        if progress:
            try:
                progress(r)
            except Exception:
                pass
    return out


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m core.topology_flood",
        description="拓扑泛洪发现：泛洪只读命令，自动推导上下级关系与拓扑图")
    parser.add_argument("--roots", default="",
                        help="指定根设备（逗号分隔，通常是核心/出口），缺省按入度自动判定")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"并发数（默认 {DEFAULT_WORKERS}）")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"单次命令超时秒数（默认 {DEFAULT_TIMEOUT}）")
    parser.add_argument("--save", action="store_true",
                        help=f"把结果落盘到 {SNAPSHOT_PATH.relative_to(BASE_DIR)}")
    parser.add_argument("--from-snapshot", action="store_true",
                        help="不泛洪，直接读上次的落盘结果并渲染")
    parser.add_argument("--mermaid-only", action="store_true",
                        help="只输出 Mermaid 图（便于贴文档）")
    parser.add_argument("--format", choices=["text", "mermaid", "dot", "json"],
                        default="text", help="输出格式")
    parser.add_argument("--device", default="",
                        help="只探测指定设备（逗号分隔的设备名），调试用")
    args = parser.parse_args(argv)

    if args.from_snapshot:
        topo = load_snapshot()
        if topo is None:
            print(f"没有找到落盘快照：{SNAPSHOT_PATH}")
            return 2
        age = snapshot_age_min()
        if age is not None:
            print(f"（快照生成于 {topo.generated}，约 {age} 分钟前）")
    else:
        from core.device_registry import list_devices
        devices = [d for d in list_devices() if d.get("transport") == "telnet"]
        if args.device:
            want = {clean_name(x) for x in args.device.split(",") if x.strip()}
            devices = [d for d in devices if clean_name(d.get("name", "")) in want]
        if not devices:
            print("没有可探测的 Telnet 设备（检查 data/device_inventory.json）")
            return 2

        def _progress(r: DeviceResult) -> None:
            flag = "✓" if r.ok else "✗"
            print(f"  {flag} {r.name:<8} {r.elapsed:>5.1f}s  {r.error}" if not r.ok
                  else f"  ✓ {r.name:<8} {r.elapsed:>5.1f}s  {r.sysname or '?'}"
                       f" / {r.model or '?'}", flush=True)

        print(f"开始泛洪发现：{len(devices)} 台设备，并发 {args.workers}…")
        roots = [x for x in args.roots.split(",") if x.strip()]
        topo = discover(devices, roots=roots or None, workers=args.workers,
                        timeout=args.timeout, save=args.save, progress=_progress)

    if args.format == "json":
        print(json.dumps(topo.to_dict(), ensure_ascii=False, indent=2))
    elif args.mermaid_only or args.format == "mermaid":
        print(render_mermaid(topo))
    elif args.format == "dot":
        print(render_dot(topo))
    else:
        print(render_text(topo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
