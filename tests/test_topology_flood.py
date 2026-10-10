"""core/topology_flood.py 的测试：解析器 / 拓扑推导 / 渲染 / 快照。

全部离线：用「假会话」按命令返回构造好的回显，不连任何真机。
"""
import pytest

from core import topology_flood as tf


# ---------------------------------------------------------------- 假设备

def make_session(raw: dict, cmd_map: dict | None = None):
    """按命令名返回对应回显的假会话。"""
    table = cmd_map or tf.FLOOD_COMMANDS

    class FakeSession:
        def __init__(self):
            self.commands: list[str] = []

        def prepare(self, disable_paging=True):
            return ""

        def exec_command(self, command, timeout=None):
            self.commands.append(command)
            for key, cmd in table.items():
                if command == cmd:
                    return raw.get(key, "")
            return ""

        def close(self):
            pass

    return FakeSession()


def devices(*names):
    return [{"name": n, "host": "192.168.10.130", "port": 2000 + i,
             "vendor": "Huawei"} for i, n in enumerate(names)]


LLDP_HEADER = "Local Intf   Neighbor Dev   Neighbor Intf   Exptime\n" + "-" * 70 + "\n"


# ---------------------------------------------------------------- 解析器

def test_parse_sysname():
    assert tf.parse_sysname("sysname SW1") == "SW1"
    assert tf.parse_sysname("#\nsysname  R2  \n#") == "R2"
    assert tf.parse_sysname("") == ""
    assert tf.parse_sysname("interface GigabitEthernet0/0/1") == ""


def test_parse_model_huwei_and_cisco():
    huawei = "VRP (R) software, Version 5.170 (S5700 V200R019C00SPC500)\nQuidway S5700-28C-HI uptime is 0 day"
    assert tf.parse_model(huawei) == "S5700-28C-HI"
    router = "Quidway AR2220 Router uptime is 1 week"
    assert tf.parse_model(router) == "AR2220"
    cisco = "cisco WS-C2960-24TT-L (PowerPC405) processor"
    assert tf.parse_model(cisco) == "WS-C2960-24TT-L"
    assert tf.parse_model("nothing useful") == ""


def test_parse_version():
    assert tf.parse_version("Version 5.170 (S5700 V200R019)") == "5.170"
    assert tf.parse_version("no version here") == ""


def test_clean_name_strips_brackets():
    assert tf.clean_name("<SW1>") == "SW1"
    assert tf.clean_name("  SW 1 ") == "SW1"
    assert tf.clean_name("[R1]") == "R1"


@pytest.mark.parametrize("raw,want", [
    ("GigabitEthernet0/0/1", "GE0/0/1"),
    ("GE0/0/2", "GE0/0/2"),
    ("Gi0/1", "GE0/1"),
    ("FastEthernet0/1", "FE0/1"),
    ("Ethernet0/0/1", "ETH0/0/1"),
    ("TenGigabitEthernet1/0/1", "XGE1/0/1"),
    ("Vlanif10", "VLANIF10"),
    ("LoopBack0", "LOOPBACK0"),
    ("GigabitEthernet0/0/1.100", "GE0/0/1.100"),
    ("NULL0", "NULL0"),
    ("", ""),
])
def test_normalize_interface(raw, want):
    assert tf.normalize_interface(raw) == want


def test_eth_trunk_not_swallowed_by_ethernet_rule():
    """Eth-Trunk 必须排在 Ethernet(Eth) 规则之前，否则会被归成 ETH1。"""
    for raw in ("Eth-Trunk1", "Eth-Trunk 1", "eth-trunk 1"):
        assert tf.normalize_interface(raw) == "ETH-TRUNK1"
    for raw in ("Bridge-Aggregation1", "Port-channel1"):
        assert tf.normalize_interface(raw) == "ETH-TRUNK1"


def test_parse_lldp_brief_wide_columns():
    text = LLDP_HEADER + ("GE0/0/1                           SW2                         "
                          "GigabitEthernet0/0/1      102\n")
    out = tf.parse_lldp_brief(text)
    assert out == [{"local": "GE0/0/1", "device": "SW2", "remote": "GE0/0/1"}]


def test_parse_lldp_brief_narrow_columns_and_empty():
    text = LLDP_HEADER + "GE0/0/1  SW2  GE0/0/1  102\n"
    assert tf.parse_lldp_brief(text)[0]["device"] == "SW2"
    assert tf.parse_lldp_brief("") == []
    # 只有表头没有数据行
    assert tf.parse_lldp_brief(LLDP_HEADER) == []


def test_parse_lldp_verbose_huwei():
    text = (
        "GE0/0/1 has 1 neighbor(s):\n"
        "Neighbor index                   :1\n"
        "    Chassis type                 :MAC address\n"
        "    System name                  : SW2\n"
        "Port ID type                     :Interface name\n"
        "Port ID                          : GigabitEthernet0/0/1\n"
    )
    out = tf.parse_lldp_verbose(text)
    assert out == [{"local": "GE0/0/1", "device": "SW2", "remote": "GE0/0/1"}]


def test_parse_cdp_neighbors_detail():
    text = (
        "-------------------------\n"
        "Device ID: SW2\n"
        "Entry address(es):\n"
        "  IP address: 10.0.0.2\n"
        "Interface: GigabitEthernet0/0/1,  Port ID (outgoing port): GigabitEthernet0/0/1\n"
    )
    out = tf.parse_lldp_verbose(text)
    assert out and out[0]["device"] == "SW2"
    assert out[0]["local"] == "GE0/0/1" and out[0]["remote"] == "GE0/0/1"


def test_parse_arp():
    text = ("IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE        INTERFACE   VPN-INSTANCE\n"
            "10.0.0.1        00e0-fc12-3456            I -S      GE0/0/1\n")
    out = tf.parse_arp(text)
    assert out == [{"ip": "10.0.0.1", "mac": "00e0fc123456", "interface": "GE0/0/1"}]
    assert tf.parse_arp("no arp entries") == []


def test_parse_mac_table():
    text = ("MAC Address       VLAN/VSI/BD        Learned-From        Type\n"
            + "-" * 70 + "\n"
            "00e0-fc12-3456    10/-/-             GE0/0/1             dynamic\n")
    out = tf.parse_mac_table(text)
    assert out[0]["mac"] == "00e0fc123456"
    assert out[0]["vlan"] == "10"
    assert out[0]["interface"] == "GE0/0/1"


def test_parse_mac_table_skips_non_port_rows():
    """CPU/聚合口之类不含 GE/FE 前缀的行要被丢掉，避免污染连线。"""
    text = ("00e0-fc12-3456    10/-/-             CPU                 dynamic\n"
            "00e0-fc12-9999    10/-/-             GE0/0/2             dynamic\n")
    out = tf.parse_mac_table(text)
    assert [e["interface"] for e in out] == ["GE0/0/2"]


def test_parse_interfaces():
    text = ("Interface                         IP Address      Physical     Protocol\n"
            "GE0/0/1                           10.0.0.1        up           up\n"
            "GE0/0/2                           unassigned      down         down\n")
    out = tf.parse_interfaces(text)
    assert out[0]["interface"] == "GE0/0/1" and out[0]["ip"] == "10.0.0.1"


def test_parse_identity_falls_back_to_prompt():
    """没读到 sysname 命令回显时，从提示符 <SW1> 里兜底取名字。"""
    res = tf.parse_identity("SW1", {"identity": "<SW9> display version\nQuidway S5700"})
    assert res.sysname == "SW9"
    assert res.model == "S5700"


# ---------------------------------------------------------------- 拓扑推导

def build(*specs, devices_list=None, roots=None, sessions=None):
    """specs: (name, lldp_text) 元组序列；返回 Topology。"""
    raw_all = {}
    devs = []
    for i, (name, lldp) in enumerate(specs):
        raw_all[name] = {"identity": "Quidway S5700-28C-HI",
                         "sysname": f"sysname {name}",
                         "lldp": lldp}
        devs.append({"name": name, "host": "h", "port": 2000 + i, "vendor": "Huawei"})
    results = []
    for d in devs:
        sess = make_session(raw_all[d["name"]])
        results.append(tf.flood_device(d, session_factory=lambda dev, t, s=sess: s))
    return tf.build_topology(results, devices=devices_list or devs, roots=roots)


def test_three_level_hierarchy():
    topo = build(
        ("R1", LLDP_HEADER + "GE0/0/0   SW1   GE0/0/1   100"),
        ("SW1", LLDP_HEADER + "GE0/0/1   R1    GE0/0/0   100\nGE0/0/2   SW2   GE0/0/1   100\n"
                             "GE0/0/3   SW3   GE0/0/1   100"),
        ("SW2", LLDP_HEADER + "GE0/0/1   SW1   GE0/0/2   100"),
        ("SW3", LLDP_HEADER + "GE0/0/1   SW1   GE0/0/3   100"),
    )
    assert set(topo.devices) == {"R1", "SW1", "SW2", "SW3"}
    assert len(topo.links) == 3
    # R1 是根（没人指向它）
    assert topo.levels["R1"] == 0
    assert topo.levels["SW1"] == 1
    assert topo.levels["SW2"] == topo.levels["SW3"] == 2
    assert topo.parents["SW1"] == "R1"
    assert topo.parents["SW2"] == "SW1"


def test_dual_link_is_two_links_not_a_loop():
    """SW1↔SW2 双链路：应记为 2 条链路，且不因互相指向而误判成环。"""
    topo = build(
        ("SW1", LLDP_HEADER + "GE0/0/1   SW2   GE0/0/1   100\nGE0/0/2   SW2   GE0/0/2   100"),
        ("SW2", LLDP_HEADER + "GE0/0/1   SW1   GE0/0/1   100\nGE0/0/2   SW1   GE0/0/2   100"),
    )
    assert len(topo.links) == 2
    # 两端互相"看到"，最终只保留两条独立链路，不产生额外环边
    assert len(topo.loop_edges) == 0


def test_isolated_device_has_no_link():
    topo = build(("SW1", LLDP_HEADER + "GE0/0/1   SW2   GE0/0/1   100"),
                 ("SW2", LLDP_HEADER + "GE0/0/1   SW1   GE0/0/1   100"),
                 ("SW3", ""))
    assert topo.roles["SW3"] == "孤立"
    assert topo.levels["SW3"] == 0
    assert any("SW3" in n for n in topo.notes)


def test_no_lldp_at_all_gives_actionable_note():
    topo = build(("SW1", ""), ("SW2", ""))
    assert topo.links == []
    assert any("lldp enable" in n for n in topo.notes)


def test_explicit_roots_overrides_inference():
    topo = build(
        ("SW1", LLDP_HEADER + "GE0/0/1   SW2   GE0/0/1   100"),
        ("SW2", LLDP_HEADER + "GE0/0/1   SW1   GE0/0/1   100"),
        roots=["SW2"],
    )
    assert topo.levels["SW2"] == 0
    assert topo.parents.get("SW1") == "SW2"


def test_failed_device_is_reported_not_crashed():
    devs = [{"name": "R1", "host": "h", "port": 9999, "vendor": "Huawei"}]

    def boom(device, timeout):
        raise OSError("连不上")

    r = tf.flood_device(devs[0], session_factory=boom)
    topo = tf.build_topology([r], devices=devs)
    assert not r.ok and "连不上" in r.error
    assert any("探测失败" in n for n in topo.notes)
    assert topo.links == []


def test_roles_core_transit_access():
    topo = build(
        ("R1", LLDP_HEADER + "GE0/0/0   SW1   GE0/0/1   100"),
        ("SW1", LLDP_HEADER + "GE0/0/1   R1    GE0/0/0   100\nGE0/0/2   SW2   GE0/0/1   100\n"
                             "GE0/0/3   SW3   GE0/0/1   100"),
        ("SW2", LLDP_HEADER + "GE0/0/1   SW1   GE0/0/2   100"),
        ("SW3", LLDP_HEADER + "GE0/0/1   SW1   GE0/0/3   100"),
    )
    assert topo.roles["R1"].startswith("出口") or topo.roles["R1"].startswith("核心")
    assert topo.roles["SW1"] == "汇聚"
    assert topo.roles["SW2"] == "接入 / 叶子"


def test_name_alias_is_resolved_to_inventory_name():
    """LLDP 报的邻居名大小写/尖括号不同，也要能归到清单里的设备。"""
    topo = build(
        ("SW1", LLDP_HEADER + "GE0/0/1   <sw2>   GE0/0/1   100"),
        ("SW2", LLDP_HEADER + "GE0/0/1   SW1   GE0/0/1   100"),
    )
    assert len(topo.links) == 1
    ends = {topo.links[0].a_device, topo.links[0].b_device}
    assert ends == {"SW1", "SW2"}


# ---------------------------------------------------------------- 渲染

def test_render_text_contains_sections():
    topo = build(
        ("SW1", LLDP_HEADER + "GE0/0/1   SW2   GE0/0/1   100"),
        ("SW2", LLDP_HEADER + "GE0/0/1   SW1   GE0/0/1   100"),
    )
    text = tf.render_text(topo)
    for section in ("设备清单", "上下级关系", "链路", "Mermaid 拓扑图"):
        assert section in text
    assert "GE0/0/1" in text


def test_render_mermaid_valid_node_ids():
    """设备名里的 '-' 等字符不能直接当 Mermaid 节点 id。"""
    topo = tf.Topology(devices=["SW-A", "R.1"], levels={"SW-A": 0, "R.1": 0},
                       roles={"SW-A": "核心 / 根", "R.1": "接入 / 叶子"})
    m = tf.render_mermaid(topo)
    assert "SW_A" in m and "R_1" in m
    assert "SW-A[" not in m
    assert m.startswith("graph TD")


def test_render_mermaid_marks_speculative_links():
    topo = tf.Topology(
        devices=["A", "B"], levels={"A": 0, "B": 1}, roles={},
        links=[tf.Link("A", "GE0/0/1", "B", "GE0/0/1", evidence="mac",
                       confidence="medium", src="A", dst="B")])
    assert "推测" in tf.render_mermaid(topo)


def test_render_dot():
    topo = tf.Topology(devices=["A", "B"], levels={"A": 0, "B": 1},
                       roles={"A": "出口 / 根", "B": "接入 / 叶子"},
                       links=[tf.Link("A", "GE0/0/1", "B", "GE0/0/1")])
    dot = tf.render_dot(topo)
    assert dot.startswith("digraph topology")
    assert '"A" -> "B"' in dot


def test_context_for_model_is_compact_and_flagged():
    topo = build(
        ("SW1", LLDP_HEADER + "GE0/0/1   SW2   GE0/0/1   100"),
        ("SW2", LLDP_HEADER + "GE0/0/1   SW1   GE0/0/1   100"),
    )
    ctx = tf.context_for_model(topo)
    assert "泛洪发现" in ctx
    assert "非人工录入" in ctx
    assert "SW1" in ctx


def test_context_for_model_truncates():
    topo = tf.Topology(devices=[f"D{i}" for i in range(200)],
                       levels={f"D{i}": i for i in range(200)})
    ctx = tf.context_for_model(topo, max_chars=200)
    assert len(ctx) <= 220
    assert "已截断" in ctx


# ---------------------------------------------------------------- 落盘

def test_snapshot_roundtrip(tmp_path):
    path = tmp_path / "topo.json"
    topo = build(
        ("SW1", LLDP_HEADER + "GE0/0/1   SW2   GE0/0/1   100"),
        ("SW2", LLDP_HEADER + "GE0/0/1   SW1   GE0/0/1   100"),
    )
    tf.save_snapshot(topo, path=path)
    back = tf.load_snapshot(path=path)
    assert back is not None
    assert back.devices == topo.devices
    assert back.levels == topo.levels
    assert len(back.links) == len(topo.links)
    assert back.links[0].a_interface == topo.links[0].a_interface


def test_load_snapshot_missing_returns_none(tmp_path):
    assert tf.load_snapshot(path=tmp_path / "nope.json") is None


def test_load_snapshot_corrupt_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json", encoding="utf-8")
    assert tf.load_snapshot(path=p) is None


# ---------------------------------------------------------------- 命令集安全

def test_all_flood_commands_are_readonly():
    """泛洪命令必须全部命中 command_guard 的 allow 级，否则会污染审计/触发确认。"""
    from core.command_guard import classify, ALLOW

    for key, cmd in tf.FLOOD_COMMANDS.items():
        verdict = classify(cmd)
        # classify 返回 dict（含 level 字段）；老版本可能是 (level, ...) 元组
        if isinstance(verdict, dict):
            level = verdict.get("level")
        elif isinstance(verdict, tuple):
            level = verdict[0]
        else:
            level = verdict
        assert level == ALLOW, f"{key} 的命令 {cmd!r} 不是只读级：{level}"


def test_cisco_command_set_uses_show():
    cmds = tf._commands_for_vendor("Cisco")
    assert cmds["identity"].startswith("show ")
    assert cmds["lldp_verbose"] == "show cdp neighbors detail" or "cdp" in cmds
    huawei = tf._commands_for_vendor("Huawei")
    assert huawei["identity"].startswith("display ")
