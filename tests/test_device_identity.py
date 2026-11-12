"""设备身份的区分能力：手册/历史必须能**认对设备**。

这一组测试对应实测发现的串味/查空风险（2026-10）：
  · 设备没绑名字时历史落在 `192.168.1.1_2001` 这类地址兜底名下，
    用 `SW1` 查就查空，模型以为没做过、然后重做一遍；
  · 用 `IP:端口` 直接查会因冒号不是合法目录名而抛错；
  · 两台设备绑同一个名字，历史写进同一个 history.jsonl（跨设备串味）；
  · 写手册时用别名会新建第二个目录，两份记录各查一半；
  · 只有历史没有手册的设备在清单里凭空消失。
"""
from __future__ import annotations

import json

import pytest

from core import device_manual
from core import device_registry as dr


@pytest.fixture
def reg(tmp_path, monkeypatch):
    """隔离 device_access.json / device_inventory.json（session 由 conftest 隔离）"""
    monkeypatch.setattr(dr, "ACCESS_PATH", tmp_path / "device_access.json")
    monkeypatch.setattr(dr, "INVENTORY_PATH", tmp_path / "device_inventory.json")
    return dr


def _inventory(path, host: str, devices: list[dict]) -> None:
    path.write_text(json.dumps({"host": host, "devices": devices}, ensure_ascii=False),
                    encoding="utf-8")


# ---------------------------------------------------------------- 解析

def test_resolve_by_name_case_port_and_sanitized(reg):
    reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    reg.bind_name("telnet", "SW2", host="10.0.0.1", port=2002)

    for q in ("SW1", "sw1", "2001", "10.0.0.1:2001", "10.0.0.1_2001"):
        r = reg.resolve_device(q)
        assert r["ok"], q
        assert r["name"] == "SW1", (q, r)


def test_resolve_bare_host_is_ambiguous_not_guessed(reg):
    reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    reg.bind_name("telnet", "SW2", host="10.0.0.1", port=2002)
    r = reg.resolve_device("10.0.0.1")
    assert r["ok"] is False
    assert r["reason"] == "ambiguous"
    assert {c["name"] for c in r["candidates"]} == {"SW1", "SW2"}


def test_resolve_unknown_lists_what_is_queryable(reg):
    reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    r = reg.resolve_device("R99")
    assert r["ok"] is False and r["reason"] == "not_found"
    assert "SW1" in r["message"] and "IP:端口" in r["message"]


def test_resolve_is_session_scoped(reg):
    device_manual.save_manual("SW9", "# SW9 设备信息\n- 型号：S5700\n", session="会话A")
    assert reg.resolve_device("SW9", "会话A")["ok"]
    # 别的会话看不到：隔离不能被「解析便利」破坏
    r = reg.resolve_device("SW9")
    assert r["ok"] is False


def test_inventory_device_resolves_by_name_and_addr(reg, tmp_path):
    _inventory(reg.INVENTORY_PATH, "10.1.1.1",
               [{"name": "CORE1", "port": 2001, "model": "S5700"}])
    assert reg.resolve_device("CORE1")["name"] == "CORE1"
    assert reg.resolve_device("10.1.1.1:2001")["name"] == "CORE1"


# ---------------------------------------------------------------- 同名保护

def test_bind_same_name_to_two_devices_disambiguates(reg):
    a = reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    b = reg.bind_name("telnet", "SW1", host="10.0.0.2", port=2001)
    assert a == "SW1"
    assert b != "SW1" and b.startswith("SW1")
    names = {e["name"] for e in json.loads(reg.ACCESS_PATH.read_text("utf-8"))["devices"].values()}
    assert len(names) == 2, names


def test_rebinding_same_address_keeps_name(reg):
    first = reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    again = reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    assert first == again == "SW1"


# ---------------------------------------------------------------- 历史

def test_history_merged_across_alias_names(reg):
    """绑定前的历史（地址兜底名）与绑定后的历史都要能被查到。"""
    device_manual.append_history("10.0.0.1_2001", "display version", "V1",
                                 transport="telnet", executed=True)
    reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    device_manual.append_history("SW1", "display current-configuration", "cfg",
                                 transport="telnet", executed=True)

    rows = device_manual.tail_history_merged(["SW1", "10.0.0.1_2001"], 10)
    # 两条记录可能落在同一秒，顺序不保证；关键是**两个目录的记录都读到了**
    assert {r["command"] for r in rows} == {"display version",
                                            "display current-configuration"}
    # 单个名字只能看到自己那份，证明合并确实生效（否则这条测试没意义）
    only_new = {r["command"] for r in device_manual.tail_history("SW1", 10)}
    assert only_new == {"display current-configuration"}


def test_recent_history_tool_accepts_address(reg):
    from mcp_tools.tools.recent_device_history import recent_device_history

    reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    device_manual.append_history("SW1", "display ip routing-table", "ok",
                                 transport="telnet", executed=True)
    out = recent_device_history("10.0.0.1:2001", 5)
    assert "SW1" in out and "display ip routing-table" in out


def test_recent_history_ambiguous_refuses(reg):
    from mcp_tools.tools.recent_device_history import recent_device_history

    reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    reg.bind_name("telnet", "SW2", host="10.0.0.1", port=2002)
    out = recent_device_history("10.0.0.1", 5)
    assert "匹配到 2 台" in out and "拒绝猜测" in out


def test_failed_command_is_not_registered_as_access(reg):
    """被拦截/连接失败的命令照样归档，但不能登记成「访问成功」。"""
    from mcp_tools.tools._archive import record_telnet

    record_telnet("10.0.0.9", 2001, "interface GigabitEthernet0/0/1", "confirm",
                  False, False, result="[需确认]", session="")
    # 没登记就不该产生访问记录文件（或至少没有任何设备条目）
    if reg.ACCESS_PATH.exists():
        assert json.loads(reg.ACCESS_PATH.read_text("utf-8"))["devices"] == {}
    rows = device_manual.tail_history("10.0.0.9_2001", 5)
    assert rows and rows[-1]["executed"] is False


# ---------------------------------------------------------------- 工具层

def test_list_manuals_shows_history_only_devices(reg):
    from mcp_tools.tools.list_device_manuals import list_device_manuals

    device_manual.append_history("SW7", "display version", "V", transport="telnet",
                                 executed=True)
    out = list_device_manuals()
    assert "只有历史" in out and "SW7" in out


def test_update_section_refuses_unknown_device(reg):
    from mcp_tools.tools.update_device_manual_section import update_device_manual_section

    out = update_device_manual_section("不存在的设备", "常用配置", "sysname X")
    assert "create_device_manual" in out
    root = device_manual.ss.session_dir() / "skill"
    assert not (root / "不存在的设备").exists(), "不能因为拼错名字就新建一台假设备"


def test_update_section_writes_under_canonical_name(reg):
    from mcp_tools.tools.update_device_manual_section import update_device_manual_section

    reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    out = update_device_manual_section("10.0.0.1:2001", "常用配置", "sysname SW1")
    assert "SW1" in out
    root = device_manual.ss.session_dir() / "skill"
    assert (root / "SW1" / "SKILL.md").is_file()
    assert not (root / "10.0.0.1:2001").exists()
    assert "sysname SW1" in (root / "SW1" / "SKILL.md").read_text(encoding="utf-8")


def test_create_manual_uses_effective_name_when_collision(reg):
    from mcp_tools.tools.create_device_manual import create_device_manual

    reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    out = create_device_manual("SW1", host="10.0.0.2", port=2001, transport="telnet")
    assert "已被另一台设备占用" in out
    # 手册只落在**实际生效的名字**上：不能出现 SW1 与 SW1-2001 两个目录各有一半记录
    effective = [e["name"] for e in
                 json.loads(reg.ACCESS_PATH.read_text("utf-8"))["devices"].values()
                 if e.get("host") == "10.0.0.2"]
    root = device_manual.ss.session_dir() / "skill"
    dirs = {p.name for p in root.iterdir() if p.is_dir()}
    assert effective and set(effective) == dirs, (dirs, effective)


# ---------------------------------------------------------------- 串口保留名

def test_serial_com_port_uses_legal_dir_name(reg):
    """COM3 是 Windows 保留名：不能当目录名，但必须是可查询的设备标识。

    此前 resolve_name 兜底返回裸 "COM3"，append_history 抛 ManualError 被静默吞掉，
    **串口通道的命令历史从项目开始就没落过盘**。修法：统一规范成 COM3-serial。
    """
    from mcp_tools.tools.create_device_manual import create_device_manual

    reg.record_access("serial", serial_port="COM3")
    assert reg.resolve_name("serial", serial_port="COM3") == "COM3-serial"
    info = reg.resolve_device("COM3", "")
    assert info["ok"] and info["name"] == "COM3-serial"

    out = create_device_manual("COM3", transport="serial", serial_port="COM3")
    assert "建档失败" not in out
    root = device_manual.ss.session_dir() / "skill"
    assert (root / "COM3-serial" / "SKILL.md").is_file()
    assert not (root / "COM3").exists()


# ---------------------------------------------------------------- 串口保留名

def test_serial_com_port_uses_legal_dir_name(reg):
    """COM3 是 Windows 保留名：不能当目录名，但必须是可查询的设备标识。

    此前 resolve_name 兜底返回裸 "COM3"，append_history 抛 ManualError 被静默吞掉，
    **串口通道的命令历史从项目开始就没落过盘**。修法：统一规范成 COM3-serial。
    """
    from mcp_tools.tools.create_device_manual import create_device_manual

    reg.record_access("serial", serial_port="COM3")
    assert reg.resolve_name("serial", serial_port="COM3") == "COM3-serial"
    info = reg.resolve_device("COM3", "")
    assert info["ok"] and info["name"] == "COM3-serial"

    out = create_device_manual("COM3", transport="serial", serial_port="COM3")
    assert "建档失败" not in out
    root = device_manual.ss.session_dir() / "skill"
    assert (root / "COM3-serial" / "SKILL.md").is_file()
    assert not (root / "COM3").exists()


# ---------------------------------------------------------------- 会话级设备清单

def test_session_devices_scoped_to_skill_dirs(reg):
    """session_devices 只返回本会话 skill 目录里的设备，并带注册表地址元数据。

    对应需求「每个会话仅展示其所属的设备记录历史」：设备页签的清单来源从
    全局台账（跨会话残留）换成 session/<sid>/skill/ 的目录扫描。
    """
    reg.bind_name("telnet", "SW1", host="10.0.0.1", port=2001)
    reg.bind_name("telnet", "R9", host="10.0.0.9", port=2009)
    reg.bind_name("telnet", "旧会话残留", host="10.0.0.99", port=2099)

    # 本会话：SW1 建了手册，R9 只有命令历史（都会被算作「出现过」）
    device_manual.ensure_manual("SW1", session="sess-a")
    device_manual.append_history("R9", "display version", session="sess-a")

    rows = reg.session_devices("sess-a")
    names = {r["name"] for r in rows}
    assert names == {"SW1", "R9"}                     # 全局台账里的残留不混入
    sw1 = next(r for r in rows if r["name"] == "SW1")
    assert sw1["host"] == "10.0.0.1" and sw1["port"] == 2001   # 探测目标可用

    # 另一个会话没有自己的记录 → 空；未打开会话（空 sid）→ 空
    assert reg.session_devices("sess-b") == []
    assert reg.session_devices("") == []
