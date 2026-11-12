"""exec 工具的复合命令逐条审计/归档 + 归档失败可区分（plan 阶段二）。

要点：
- 复合命令（`;`/换行）逐条执行后，history.jsonl 必须**每条一行**，
  而不是只记整串——否则复盘/SFT 数据集都对不上「实际下发了什么」。
- 中途失败：已执行的记 executed=True，失败那条与后续记 executed=False。
- 归档失败：命令结论不受影响，但返回空串 + 告警行写入 archive_errors.log，
  工具回显必须明示「部分历史归档失败」，不伪装成完整成功。
"""
from __future__ import annotations

import json

import pytest


class _FakeSession:
    """记录 exec_command 调用；可指定第几条抛异常。"""

    def __init__(self, fail_at: int | None = None):
        self.calls: list[str] = []
        self.fail_at = fail_at

    def exec_command(self, command: str, timeout: int = 20) -> str:
        self.calls.append(command)
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise ConnectionError("link down")
        return f"OK:{command}"

    def close(self) -> None:
        pass


def _history_rows():
    from core import session_skills as ss

    root = ss.session_dir(ss.current())
    hist = root / "skill"
    rows = []
    if not hist.exists():
        return rows
    for dev in hist.iterdir():
        f = dev / "history.jsonl"
        if f.is_file():
            rows.extend(json.loads(ln) for ln in f.read_text("utf-8").splitlines() if ln)
    return rows


@pytest.fixture()
def _capture(monkeypatch):
    """拦截 open_telnet/open_serial 与 audit，避免真实连接与审计日志。"""
    from core import command_guard, device_conn

    holder: dict = {"sess": None, "audits": [], "opened": 0}

    def fake_open_telnet(host, **kwargs):
        holder["opened"] += 1
        if holder["sess"] is None:
            holder["sess"] = _FakeSession()
        return holder["sess"]

    def fake_open_serial(port, **kwargs):
        holder["opened"] += 1
        if holder["sess"] is None:
            holder["sess"] = _FakeSession()
        return holder["sess"]

    def fake_audit(command, decision, **kwargs):
        holder["audits"].append({"command": command, **kwargs})

    monkeypatch.setattr(device_conn, "open_telnet", fake_open_telnet)
    monkeypatch.setattr(device_conn, "open_serial", fake_open_serial)
    monkeypatch.setattr(command_guard, "audit", fake_audit)
    return holder


def test_compound_command_archived_per_part(_capture):
    from mcp_tools.tools.exec_telnet_command import exec_telnet_command

    out = exec_telnet_command("display version; display clock",
                              host="10.0.0.51", port=2001)
    assert "OK:display version" in out and "OK:display clock" in out
    rows = [r for r in _history_rows() if r["transport"] == "telnet"]
    assert {r["command"] for r in rows} == {"display version", "display clock"}
    assert all(r["executed"] for r in rows)
    # 逐条审计：audit 收到的是拆分后的每一条，不是整串
    assert {a["command"] for a in _capture["audits"]} == {
        "display version", "display clock"}
    assert "2/2 条历史" in out


def test_compound_midway_failure_marks_rest_unexecuted(_capture):
    from mcp_tools.tools.exec_telnet_command import exec_telnet_command

    _capture["sess"] = _FakeSession(fail_at=2)
    out = exec_telnet_command("display version; display clock; display vlan",
                              host="10.0.0.52", port=2001)
    rows = {r["command"]: r for r in _history_rows() if r["transport"] == "telnet"}
    assert rows["display version"]["executed"] is True
    assert rows["display clock"]["executed"] is False          # 下发时链路断了
    assert rows["display vlan"]["executed"] is False           # 未执行也要留痕
    assert "未执行" in rows["display vlan"]["result"]
    assert "OK:display version" in out and "link down" in out


def test_connection_failure_records_whole_command_as_not_executed(_capture, monkeypatch):
    from core import device_conn
    from mcp_tools.tools.exec_telnet_command import exec_telnet_command

    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(device_conn, "open_telnet", boom)
    out = exec_telnet_command("display version", host="10.0.0.53", port=2001)
    assert "Telnet 执行失败" in out
    rows = [r for r in _history_rows() if r["transport"] == "telnet"]
    assert rows and rows[-1]["executed"] is False


def test_archive_failure_is_distinguishable(_capture, monkeypatch, tmp_path):
    from core import device_manual
    from mcp_tools.tools import _archive
    from mcp_tools.tools.exec_telnet_command import exec_telnet_command

    warn_log = tmp_path / "archive_errors.log"
    monkeypatch.setattr(_archive, "WARN_LOG", warn_log)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(device_manual, "append_history", boom)
    out = exec_telnet_command("display version; display clock",
                              host="10.0.0.54", port=2001)
    # 命令结论不受影响
    assert "OK:display version" in out
    # 但不伪装成完整成功：明示归档失败 + 告警行可追溯
    assert "归档失败" in out
    assert warn_log.is_file() and "archive_failed" in warn_log.read_text("utf-8")


def test_serial_com_port_history_archived(_capture):
    """COMx 是 Windows 保留名：此前 resolve_name 兜底返回裸 "COM3"，
    safe_name 拒收 → append_history 静默返回空串，串口历史从未归档过。
    现在必须落到合法目录名 COM3-serial。"""
    from core import device_registry
    from mcp_tools.tools.exec_command import exec_command

    assert device_registry.resolve_name("serial", serial_port="COM3") == "COM3-serial"
    exec_command("display version", port="COM3")
    rows = _history_rows()
    assert rows and rows[-1]["device"] == "COM3-serial"
    assert rows[-1]["executed"] is True
    # 查询端也要闭环：用户说「COM3」能读到 COM3-serial 目录下的历史
    from mcp_tools.tools.recent_device_history import recent_device_history

    out = recent_device_history("COM3", 5)
    assert "display version" in out and "COM3-serial" in out


def test_serial_compound_archived_per_part(_capture):
    from mcp_tools.tools.exec_command import exec_command

    out = exec_command("display version; display clock", port="COM3")
    assert "OK:display version" in out and "OK:display clock" in out
    rows = [r for r in _history_rows() if r["transport"] == "serial"]
    assert {r["command"] for r in rows} == {"display version", "display clock"}
    assert "2/2 条历史" in out
