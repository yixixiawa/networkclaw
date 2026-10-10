"""审计日志轮转测试：写入超限自动切分、tail 跨轮转文件读取、失败不抛异常。

不碰真实 logs/command_audit.log——用 monkeypatch 把 AUDIT_LOG 指到临时目录，
并用环境变量把阈值压到几十字节，几次写入就能触发轮转。
"""
import json

import pytest

from core import command_guard as cg


@pytest.fixture()
def audit_env(tmp_path, monkeypatch):
    """把审计日志指向临时文件，并设置很小的轮转阈值。"""
    log = tmp_path / "command_audit.log"
    monkeypatch.setattr(cg, "AUDIT_LOG", log)
    monkeypatch.setattr(cg, "AUDIT_MAX_BYTES", 300)
    monkeypatch.setattr(cg, "AUDIT_BACKUPS", 2)
    return log


def _write_n(log, n, prefix="display version"):
    d = {"level": "allow", "reason": "只读"}
    for i in range(n):
        cg.audit(f"{prefix} {i}", d, transport="telnet", target="1.1.1.1:23",
                 confirmed=False, executed=True)


def test_rotation_creates_backups_and_caps_size(audit_env):
    log = audit_env
    _write_n(log, 20)
    assert log.exists(), "当前日志文件应存在"
    assert log.stat().st_size <= cg.AUDIT_MAX_BYTES + 200, "单文件不应无限增长"
    backups = sorted(p.name for p in log.parent.iterdir())
    assert "command_audit.log.1" in backups
    # 备份份数不超过 AUDIT_BACKUPS
    numbered = [b for b in backups if b.rsplit(".", 1)[-1].isdigit()]
    assert len(numbered) <= cg.AUDIT_BACKUPS


def test_rotation_zero_backups_truncates(audit_env, monkeypatch):
    """BACKUPS=0 时不保留历史：直接清空当前文件。"""
    log = audit_env
    monkeypatch.setattr(cg, "AUDIT_BACKUPS", 0)
    _write_n(log, 20)
    assert log.exists()
    assert not list(log.parent.glob("command_audit.log.*")), "不应产生备份文件"


def test_audit_tail_spans_rotated_files(audit_env):
    """轮转后 tail 仍能取到最近的记录（读当前文件 + 备份，而非只读当前）。"""
    log = audit_env
    _write_n(log, 20, prefix="cmd")
    tail = cg.audit_tail(5)
    assert 1 <= len(tail) <= 5
    # 末条应当是最后写入的那条
    assert tail[-1]["command"] == "cmd 19"
    # 返回顺序是从旧到新
    assert [r["command"] for r in tail] == sorted(
        (r["command"] for r in tail), key=lambda c: int(c.split()[-1]))


def test_audit_tail_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cg, "AUDIT_LOG", tmp_path / "nope.log")
    assert cg.audit_tail(10) == []


def test_audit_records_are_jsonl(audit_env):
    log = audit_env
    cg.audit("sysname SW1", {"level": "confirm", "reason": "配置类"},
             transport="serial", target="COM3", confirmed=True, executed=True)
    row = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["command"] == "sysname SW1"
    assert row["level"] == "confirm"
    assert row["transport"] == "serial"
    assert row["executed"] is True


def test_audit_never_raises_on_bad_path(tmp_path, monkeypatch):
    """审计失败绝不能影响主流程：路径不可写时应静默返回。"""
    bad = tmp_path / "afile"
    bad.write_text("占位", encoding="utf-8")       # 用文件占住目录位置
    monkeypatch.setattr(cg, "AUDIT_LOG", bad / "sub" / "x.log")
    cg.audit("display version", {"level": "allow"}, transport="telnet",
             target="t", confirmed=False, executed=True)   # 不抛异常即通过


def test_tail_lines_only_reads_tail(tmp_path):
    """_tail_lines 只应返回末尾 n 行，且能处理无结尾换行的文件。"""
    f = tmp_path / "x.log"
    f.write_text("\n".join(f"line{i}" for i in range(100)), encoding="utf-8")
    assert cg._tail_lines(f, 3) == ["line97", "line98", "line99"]
    assert cg._tail_lines(f, 0) == []
    assert cg._tail_lines(tmp_path / "missing.log", 3) == []
