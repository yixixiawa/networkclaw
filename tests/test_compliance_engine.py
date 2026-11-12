"""等保规则引擎：规则加载、按设备大类过滤、配置求值、批量扫描编排。"""
from __future__ import annotations

from core import compliance
from core.compliance import evaluate, load_rules, rules_for


def test_load_rules_from_repo():
    rules = load_rules()
    assert len(rules) >= 50                      # 当前规则库 56 条
    assert all(r.get("id") for r in rules)


def test_rules_for_maps_kinds():
    rules = load_rules()
    assert rules_for(rules, "unknown") == []     # 识别不了不套规则（宁漏勿误报）
    sw = rules_for(rules, "switch")
    rt = rules_for(rules, "router")
    fw = rules_for(rules, "firewall")
    assert sw and sw == rt                       # network_device 覆盖 switch+router
    assert fw != sw


RULE = {"id": "T-1", "control_point": "访问控制", "requirement": "应有 ACL",
        "severity": "high", "device_type": "network_device",
        "remediation": ["acl 3000"], "evidence_hint": "display acl all",
        "check": {"type": "config_regex", "target": "running-config",
                  "expect": "存在绑定接口的 ACL", "pattern": "traffic-filter\\s+.*acl"}}


def test_evaluate_pass_and_fail():
    ok = evaluate("interface G0/0/1\n traffic-filter inbound acl 3000\n", [RULE])
    bad = evaluate("sysname SW1\n", [RULE])
    assert ok["passed"] == 1 and ok["failures"] == []
    assert bad["passed"] == 0 and len(bad["failures"]) == 1
    f = bad["failures"][0]
    assert f["id"] == "T-1" and f["severity"] == "high"
    assert f["remediation"] == ["acl 3000"]


def test_manual_confirm_never_counts_as_failure():
    r = {**RULE, "check": {"type": "manual_confirm", "target": "running-config",
                           "expect": "人工核对"}}
    rep = evaluate("anything", [r])
    assert rep["failures"] == [] and rep["manual"] == 1


def test_broken_regex_degrades_to_manual_not_crash():
    r = {**RULE, "check": {"type": "config_regex", "pattern": "([unclosed"}}
    rep = evaluate("x", [r])
    assert rep["failures"] == [] and rep["manual"] == 1


def test_failures_sorted_high_first():
    rules = [
        {**RULE, "id": "T-low", "severity": "low"},
        {**RULE, "id": "T-high", "severity": "high"},
    ]
    rep = evaluate("", rules)
    assert [f["id"] for f in rep["failures"]] == ["T-high", "T-low"]


def test_scan_devices_happy_and_error_paths(monkeypatch):
    devs = [
        {"host": "10.0.0.1", "port": 2001, "name": "SW1",
         "model": "S5700-28C-HI", "transport": "telnet", "vendor": "huawei"},
        {"host": "10.0.0.2", "port": 2002, "name": "BAD",
         "model": "AR2220", "transport": "telnet", "vendor": "huawei"},
    ]
    monkeypatch.setattr(compliance, "collect_config",
                        lambda d, timeout=25.0: (
                            "traffic-filter inbound acl 3000"
                            if d["name"] == "SW1" else
                            (_ for _ in ()).throw(OSError("connection refused"))))
    rep = compliance.scan_devices(devs, rules=[RULE])
    assert len(rep["results"]) == 2
    sw1 = next(r for r in rep["results"] if r["name"] == "SW1")
    bad = next(r for r in rep["results"] if r["name"] == "BAD")
    assert sw1["high"] == 0 and sw1["passed"] == 1 and sw1["error"] == ""
    assert "connection refused" in bad["error"] and bad["failures"] == []


def test_scan_skips_unknown_kind(monkeypatch):
    devs = [{"host": "10.0.0.9", "port": 2009, "name": "MIST",
             "model": "", "transport": "telnet", "vendor": ""}]
    monkeypatch.setattr(compliance, "collect_config",
                        lambda d, timeout=25.0: "x")   # 不该被调用到
    rep = compliance.scan_devices(devs, rules=[RULE])
    assert rep["results"][0]["error"]                     # 明确说明跳过原因
    assert rep["results"][0]["failures"] == []
