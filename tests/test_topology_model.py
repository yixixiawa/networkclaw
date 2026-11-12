"""拓扑数据模型：快照 + 注册表 → 节点/边；型号识别与大类分类。"""
from __future__ import annotations

import json
from pathlib import Path

from core.topology_model import classify, load_topology_model


def _write_snapshot(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "topology_discovered.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


SNAP = {
    "devices": ["10.0.0.1:2001", "10.0.0.2:2002", "10.0.0.3:2003"],
    "links": [{"a_device": "10.0.0.1:2001", "a_interface": "GE0/0/1",
               "b_device": "10.0.0.2:2002", "b_interface": "GE0/0/2",
               "evidence": "lldp", "confidence": "high"}],
    "roles": {"10.0.0.1:2001": "核心 / 根", "10.0.0.2:2002": "接入 / 叶子",
              "10.0.0.3:2003": "孤立"},
    "levels": {"10.0.0.1:2001": 0, "10.0.0.2:2002": 1, "10.0.0.3:2003": 99},
    "results": [
        {"name": "10.0.0.1:2001", "sysname": "SW1", "model": "S5700-28C-HI"},
        {"name": "10.0.0.2:2002", "sysname": "AR1", "model": "AR2220"},
        {"name": "10.0.0.3:2003", "sysname": "FW0", "model": ""},
    ],
    "generated": "2026-10-30 10:00:00",
}


def test_classify_by_model_then_sysname():
    assert classify("S5700-28C-HI") == "switch"
    assert classify("AR2220") == "router"
    # 无型号：sysname 前缀兜底
    assert classify("", "SW3") == "switch"
    assert classify("", "FW0") == "firewall"
    assert classify("", "AR1") == "router"
    assert classify("", "box") == "unknown"


def test_load_model_nodes_and_edges(tmp_path):
    m = load_topology_model(snapshot_path=_write_snapshot(tmp_path, SNAP), registry=[])
    assert m["ok"] and m["error"] == ""
    assert len(m["nodes"]) == 3 and len(m["edges"]) == 1
    sw1 = next(n for n in m["nodes"] if n["name"] == "SW1")
    assert sw1["model"] == "S5700-28C-HI" and sw1["kind"] == "switch"
    assert sw1["level"] == 0 and sw1["host"] == "10.0.0.1" and sw1["port"] == 2001
    e = m["edges"][0]
    assert e["a"] == "10.0.0.1:2001" and e["b_if"] == "GE0/0/2"


def test_stale_registry_devices_not_merged_into_snapshot(tmp_path):
    """快照有效时，注册表里的 Telnet 台账设备不得混进拓扑。

    台账（device_access.json）记的是历史上连过的所有设备，跨实验残留
    （曾把另一套 10.0.0.x 实验的 25 台无连线节点混进当前拓扑）。
    只有注册表里的**串口**设备才允许补充进快照视图。
    """
    reg = [
        {"key": "10.0.0.54:2001", "host": "10.0.0.54", "port": 2001,
         "transport": "telnet", "name": "旧实验残留"},
        {"key": "serial:COM3", "transport": "serial", "serial_port": "COM3",
         "name": "串口设备"},
    ]
    m = load_topology_model(snapshot_path=_write_snapshot(tmp_path, SNAP), registry=reg)
    names = [n["key"] for n in m["nodes"]]
    assert "10.0.0.54:2001" not in names          # 残留台账不混入
    assert "serial:COM3" in names                 # 串口设备补充进来
    assert len(names) == 4


def test_missing_snapshot_falls_back_to_registry(tmp_path):
    """快照缺失时整体降级为注册表清单（无连线），而不是报错空白。"""
    reg = [{"key": "10.0.0.9:2009", "host": "10.0.0.9", "port": 2009,
            "transport": "telnet", "name": "R9", "model": "AR2220"}]
    m = load_topology_model(snapshot_path=tmp_path / "nope.json", registry=reg)
    assert m["ok"] is True and len(m["nodes"]) == 1 and m["edges"] == []
    assert m["nodes"][0]["model"] == "AR2220"
    assert "快照不存在" in m["error"]
    # 注册表也空：才是彻底的不可用
    m2 = load_topology_model(snapshot_path=tmp_path / "nope.json", registry=[])
    assert m2["ok"] is False and m2["nodes"] == []


def test_corrupt_snapshot_does_not_crash(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    m = load_topology_model(snapshot_path=p, registry=[])
    assert m["nodes"] == [] and "解析失败" in m["error"]


def test_model_inferred_from_echo_features(tmp_path):
    """eNSP 模板横幅抓不到型号时按回显特征推断，全部带（推测）后缀。"""
    snap = {
        "devices": ["10.0.0.1:2000", "10.0.0.2:2012", "10.0.0.3:2003"],
        "links": [], "roles": {}, "levels": {},
        "results": [
            # USG 防火墙：VRP WVSP 分支横幅 + 无型号
            {"name": "10.0.0.1:2000", "sysname": "FW0", "model": "", "ok": True,
             "raw": {"identity": "VRP WVSP Software Version VRPV500R003C07",
                     "interfaces": "GigabitEthernet0/0/0"}},
            # eNSP 模板横幅 + 串口路由器
            {"name": "10.0.0.2:2012", "sysname": "R12", "model": "", "ok": True,
             "raw": {"identity": "Version 5.110 (eNSP V100R001C00)",
                     "interfaces": "Serial0/0/0 Ethernet0/0/0"}},
            # 登录失败：不给型号，标明原因
            {"name": "10.0.0.3:2003", "sysname": "", "model": "", "ok": False,
             "error": "DeviceError: 登录后未识别到设备提示符", "raw": {}},
        ],
        "generated": "t",
    }
    m = load_topology_model(snapshot_path=_write_snapshot(tmp_path, snap), registry=[])
    models = {n["key"]: n["model"] for n in m["nodes"]}
    assert models["10.0.0.1:2000"] == "USG6000V（推测）"
    assert models["10.0.0.2:2012"] == "AR 系列（推测）"
    assert models["10.0.0.3:2003"] == "未知（登录失败）"


def test_serial_key_becomes_node_without_crash(tmp_path):
    """串口键 serial:COM3 / COM3-serial 不是 host:port 结构，端口记 0 不炸。"""
    snap = {"devices": ["serial:COM3"], "links": [], "roles": {}, "levels": {},
            "results": [{"name": "serial:COM3", "sysname": "CONSOLE", "model": ""}],
            "generated": "t"}
    m = load_topology_model(snapshot_path=_write_snapshot(tmp_path, snap), registry=[])
    assert m["ok"] and m["nodes"][0]["port"] == 0
    assert m["nodes"][0]["host"] == "serial:COM3"


# ---------------------------------------------------------------- 会话隔离

def test_session_snapshot_preferred_over_global(tmp_path, monkeypatch):
    """会话目录里有自己的快照时优先用它（discover_topology 会落会话副本）。"""
    from core import session_skills as ss
    import core.topology_model as tm

    monkeypatch.setattr(ss, "SESSIONS_DIR", tmp_path / "session")
    sp = ss.session_dir("sess-a") / "topology_discovered.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({
        "devices": ["10.9.9.9:2999"], "links": [], "roles": {}, "levels": {},
        "results": [{"name": "10.9.9.9:2999", "sysname": "SW9", "model": "S5700"}],
        "generated": "2026-11-11 22:00:00",
    }, ensure_ascii=False), encoding="utf-8")

    m = load_topology_model(snapshot_path=None, session="sess-a", registry=[])
    assert [n["name"] for n in m["nodes"]] == ["SW9"]
    assert m["generated"] == "2026-11-11 22:00:00"


def test_session_filter_keeps_only_session_devices(tmp_path):
    """会话过滤：只留本会话的设备，边只留两端都留下的。"""
    m = load_topology_model(snapshot_path=_write_snapshot(tmp_path, SNAP),
                            session="sess-a", registry=[],
                            session_devices=["SW1", "10.0.0.1:2001"])
    assert [n["name"] for n in m["nodes"]] == ["SW1"]
    assert m["filtered"] == 2
    # SW1—AR1 的边因 AR1 被过滤掉而整条丢弃
    assert m["edges"] == []


def test_session_filter_matches_registry_aliases(tmp_path):
    """会话设备给的是名字，快照键是地址：经注册表别名也能对上。"""
    reg = [{"key": "10.0.0.1:2001", "host": "10.0.0.1", "port": 2001,
            "transport": "telnet", "name": "SW1", "aliases": ["SW1", "10.0.0.1:2001"]}]
    m = load_topology_model(snapshot_path=_write_snapshot(tmp_path, SNAP),
                            session="sess-a", registry=reg,
                            session_devices=["SW1"])
    assert [n["name"] for n in m["nodes"]] == ["SW1"]


def test_session_without_devices_shows_guidance(tmp_path):
    """本会话还没碰过设备：不留全局残留节点，给一句可执行的指引。"""
    m = load_topology_model(snapshot_path=_write_snapshot(tmp_path, SNAP),
                            session="fresh", registry=[], session_devices=[])
    assert m["nodes"] == [] and m["edges"] == [] and m["ok"] is False
    assert "本会话" in m["error"]


def test_no_session_keeps_legacy_behavior(tmp_path):
    """session 为空（CLI/旧调用方）不做会话过滤，行为与之前一致。"""
    m = load_topology_model(snapshot_path=_write_snapshot(tmp_path, SNAP), registry=[])
    assert len(m["nodes"]) == 3 and "session" in m and m["session"] == ""
