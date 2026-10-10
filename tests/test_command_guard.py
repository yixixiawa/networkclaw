"""命令安全网关 core/command_guard.py 的分级与裁决测试。

约定（三级策略，详见 core/command_guard.py 模块文档）：
    allow    只读：display / show / ping / tracert ...
    confirm  配置类 + **未匹配任何规则的命令**（保守兜底）
    block    破坏性：undo / no / shutdown / reset / save ...（confirmed=True 也硬拦）
"""
import pytest

from core import command_guard as cg


@pytest.fixture(autouse=True)
def _reset_experiment_mode():
    """实验模式是全局状态，测完必须还原，避免污染其他用例。"""
    cg.set_experiment_mode(False)
    yield
    cg.set_experiment_mode(False)


# ---------------------------------------------------------------- allow
@pytest.mark.parametrize("cmd", [
    "display current-configuration",
    "display version",
    "show version",
    "ping 127.0.0.1",
    "tracert 1.1.1.1",
    "screen-length 0 temporary",
])
def test_allow_readonly(cmd):
    assert cg.classify(cmd)["level"] == cg.ALLOW


# ---------------------------------------------------------------- confirm
@pytest.mark.parametrize("cmd", [
    "sysname SW1",
    "vlan batch 10 20",
    "interface GigabitEthernet0/0/1",
    "ospf 1 router-id 1.1.1.1",
    "完全没见过的命令",          # 未匹配任何规则 -> 保守归入 confirm
])
def test_confirm_by_default(cmd):
    assert cg.classify(cmd)["level"] == cg.CONFIRM


def test_confirm_requires_user_consent():
    ok, _, d = cg.check("sysname SW1")
    assert not ok and d["level"] == cg.CONFIRM
    ok, text, _ = cg.check("sysname SW1", confirmed=True)
    assert ok and "已确认" in text


# ---------------------------------------------------------------- block
@pytest.mark.parametrize("cmd", [
    "undo vlan 2",
    "no shutdown",
    "negate 1",
    "shutdown",
    "delete flash:/vrpcfg.zip",
    "reset saved-configuration",
    "reboot",
    "save",
    "format flash:",
])
def test_block_hard_even_with_confirm(cmd):
    ok, _, d = cg.check(cmd, confirmed=True)
    assert not ok and d["level"] == cg.BLOCK


def test_undo_downgraded_to_confirm_in_experiment_mode():
    """实验模式：undo/no 降级为「需确认」——隔离拓扑里必须能清理旧配置。"""
    cg.set_experiment_mode(True)
    assert cg.classify("undo vlan 2")["level"] == cg.CONFIRM
    assert cg.classify("no shutdown")["level"] == cg.CONFIRM


# ---------------------------------------------------------------- 多命令
def test_multi_command_takes_highest_level():
    assert cg.classify("display version ; undo vlan 2")["level"] == cg.BLOCK
    assert cg.classify("display version ; sysname SW1")["level"] == cg.CONFIRM
    assert cg.classify("display version ; ping 1.1.1.1")["level"] == cg.ALLOW


def test_classify_parts_report_each_subcommand():
    d = cg.classify("display version ; sysname SW1")
    assert len(d["parts"]) == 2
    levels = {p["level"] for p in d["parts"]}
    assert levels == {cg.ALLOW, cg.CONFIRM}


def test_empty_command_is_allow():
    assert cg.classify("")["level"] == cg.ALLOW
