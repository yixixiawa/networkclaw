"""等保2.0 规则集的结构与可执行性测试。

守什么：
    1. 契约字段齐全（id/vendor/device_type/category/control_point/requirement/
       weight_level/severity/source/check/remediation/evidence_hint）
    2. check.type 只能是约定的五种
    3. severity 必须由 weight_level 对应权重推导得出，不能手填
    4. remediation 每条命令都能在 command_templates.csv 或测评表原文找到出处
    5. manual_confirm 必须写明需要什么证据（长度门槛 + 不含"建议加强"类糊弄词）
    6. 规则真的能跑：规范配置 pass、裸奔配置 fail（防止正则永远匹配不上）
    7. rules_index.json 与实际文件一致

为什么不测具体某条规则的正则字符串：
    那是实现细节，改一个字就要改测试，维护成本高且测不出真问题。
    这里测的是「行为」——给两段配置，看结论对不对。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "tools"))

from _verify_remediation_source import SourceIndex  # noqa: E402

RULE_DIR = BASE / "knowledge" / "compliance" / "dengbao_rules"
ALLOWED_TYPES = {
    "config_contains", "config_absent", "config_regex",
    "config_value_compare", "manual_confirm",
}
REQUIRED_FIELDS = [
    "id", "vendor", "device_type", "category", "control_point", "requirement",
    "weight_level", "severity", "source", "check", "remediation", "evidence_hint",
]
# 交付验收明确禁止的表述
VAGUE_WORDS = ["建议加强", "根据实际情况", "视情况", "酌情", "尽可能"]


def _rule_files() -> list[Path]:
    return sorted(p for p in RULE_DIR.glob("*.yaml"))


@pytest.fixture(scope="module")
def rules() -> list[dict]:
    out = []
    for f in _rule_files():
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        d["_file"] = f.name
        out.append(d)
    return out


def test_rule_dir_not_empty(rules):
    assert len(rules) >= 50, f"规则数量异常偏少：{len(rules)}"


def test_every_rule_has_required_fields(rules):
    for r in rules:
        for k in REQUIRED_FIELDS:
            assert k in r, f"{r.get('id', r['_file'])} 缺字段 {k}"
            assert r[k] not in (None, "", [], {}), f"{r.get('id')} 字段 {k} 为空"


def test_id_matches_filename(rules):
    for r in rules:
        assert f"{r['id']}.yaml" == r["_file"], f"文件名与 id 不符：{r['_file']} vs {r['id']}"


def test_ids_unique(rules):
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)), "存在重复 id"


def test_check_type_in_allowed_set(rules):
    for r in rules:
        t = r["check"]["type"]
        assert t in ALLOWED_TYPES, f"{r['id']} 非法 check.type: {t}"
        # 非 manual_confirm 必须给出 pattern
        if t != "manual_confirm":
            assert r["check"].get("pattern"), f"{r['id']} 缺 pattern"


def test_weight_level_valid(rules):
    for r in rules:
        assert r["weight_level"] in (2, 3), f"{r['id']} weight_level 只能是 2 或 3"


def test_severity_derived_from_weight(rules):
    """severity 必须与权重一致：1→high，0.7→medium，0.4→low。"""
    mapping = {1: "high", 0.7: "medium", 0.4: "low"}
    for r in rules:
        wd = r.get("weight_detail") or {}
        w = wd.get(f"level{r['weight_level']}")
        assert w is not None, f"{r['id']} 缺对应等级的权重值"
        assert r["severity"] == mapping[w], (
            f"{r['id']} severity={r['severity']} 与权重 {w} 不符（应为 {mapping[w]}）"
        )


def test_source_cites_line_number(rules):
    for r in rules:
        assert "行" in r["source"], f"{r['id']} 的 source 未给出行号/测评项编号：{r['source']}"


def test_manual_confirm_has_evidence(rules):
    """manual_confirm 分两类，要求不同：

    ① 真·待取证（默认）：必须写清要什么证据、怎么取。
    ② 资料原文判「不适用」：断言的是"这条要求对网络设备不成立"，
       不需要取证动作，但**必须引用原文出处**（否则就成了凭空跳过）。
    """
    na_keywords = ("此项不适用", "此项不适合", "not_applicable", "不适用")
    for r in rules:
        if r["check"]["type"] != "manual_confirm":
            continue
        hint = r["evidence_hint"]
        assert len(hint) >= 40, f"{r['id']} 的 manual_confirm 未说明需要什么证据"

        is_na = any(k in hint for k in na_keywords)
        if is_na:
            # 不适用条目：必须指明是哪份资料哪一行说的
            assert ("行" in hint) or ("表" in hint), \
                f"{r['id']} 判不适用但没引用资料出处：{hint[:80]}"
            continue

        # 待取证条目：必须给可执行动作
        assert any(k in hint for k in ("需要", "取证", "证据", "截图")), \
            f"{r['id']} 的 evidence_hint 没有可执行的取证动作"


def test_no_vague_wording(rules):
    for r in rules:
        blob = r["requirement"] + r["evidence_hint"] + " ".join(r["remediation"])
        for w in VAGUE_WORDS:
            assert w not in blob, f"{r['id']} 含无法执行的表述『{w}』"


def test_remediation_commands_have_source(rules):
    """核心约束：不允许编造命令。逐条核对出处。

    原文行来自 `knowledge/compliance/dengbao_source_lines.json`（由
    `tools/build_dengbao_rules.py` 从三份 xlsx 抽取并逐行去重）。
    不直接读 xlsx 的原因：项目 venv 无 openpyxl，直接读会让这条**最关键的**
    约束在 CI 里被 skip —— 那等于没守。
    """
    src = BASE / "knowledge" / "compliance" / "dengbao_source_lines.json"
    assert src.exists(), f"缺原文存档 {src}，先跑 tools/build_dengbao_rules.py"
    kb_blob = "\n".join(json.loads(src.read_text(encoding="utf-8"))["lines"])
    idx = SourceIndex(kb_blob=kb_blob)

    missing = []
    for r in rules:
        for cmd in r["remediation"]:
            ok, how = idx.check(cmd)
            if not ok:
                missing.append(f"{r['id']}: {cmd!r} ({how})")
    assert not missing, "以下 remediation 命令在资料中找不到出处：\n" + "\n".join(missing)


# ---------------------------------------------------------------- 行为测试
GOOD = """
sysname CoreSW
aaa
 local-user netadmin password irreversible-cipher Huawei@123
 local-user netadmin service-type ssh
 local-user netadmin privilege level 15
 local-user audit password irreversible-cipher Audit@12345
 local-user audit privilege level 5
acl 2001
 rule 10 permit source 10.1.100.0 0.0.0.255
acl 3000
 rule 10 permit tcp source 10.1.100.0 0.0.0.255 destination 192.168.1.10 0 destination-port eq 3389
interface GigabitEthernet0/0/1
 shutdown
traffic-filter outbound acl 3000
user-interface vty 0 4
 authentication-mode aaa
 protocol inbound ssh
 acl 2001 inbound
 idle-timeout 5
stelnet server enable
ssh server acl 2001
info-center enable
info-center loghost 192.10.12.1 facility local 1
logging host 192.10.12.1
info-center timestamp log date precision-time millisecond
"""

BARE = """
sysname SW1
vlan batch 10 20
interface Vlanif10
 ip address 192.168.1.1 24
interface GigabitEthernet0/0/1
 port link-type access
 port default vlan 10
ospf 1 router-id 1.1.1.1
"""

ANY_ANY = """
acl 3000
 rule 5 permit ip any any
interface GigabitEthernet0/0/1
 traffic-filter outbound acl 3000
"""


def _eval(rule: dict, config: str) -> str:
    """极简判定器：只实现 config_* 三类，用于验证正则方向性。"""
    chk = rule["check"]
    t = chk["type"]
    pat = chk.get("pattern") or ""
    if t == "manual_confirm":
        return "unknown"
    if not pat:
        return "unknown"
    m = re.search(pat, config, re.MULTILINE)
    if t == "config_absent":
        return "fail" if m else "pass"
    return "pass" if m else "fail"


def test_auto_rules_pass_on_good_config(rules):
    bad = []
    for r in rules:
        if r["check"]["type"] == "manual_confirm":
            continue
        if _eval(r, GOOD) != "pass":
            bad.append(r["id"])
    assert not bad, f"规范配置下这些规则未通过：{bad}"


def test_auto_rules_fail_on_bare_config(rules):
    bad = []
    for r in rules:
        if r["check"]["type"] == "manual_confirm":
            continue
        if _eval(r, BARE) != "fail":
            bad.append(r["id"])
    assert not bad, f"裸奔配置下这些规则竟然通过（疑似恒 pass）：{bad}"


def test_any_any_is_detected(rules):
    """全通策略必须被判 fail —— 防止负向断言跨行失效。"""
    target = [r for r in rules if r["id"] == "DB-BND-AC-02"]
    assert target, "缺少 DB-BND-AC-02"
    assert _eval(target[0], ANY_ANY) == "fail", "含 permit ip any any 时未判 fail"
    assert _eval(target[0], GOOD) == "pass", "无全通策略时未判 pass"


def test_manual_rules_return_unknown(rules):
    for r in rules:
        if r["check"]["type"] != "manual_confirm":
            continue
        assert _eval(r, GOOD) == "unknown"


# ---------------------------------------------------------------- 索引一致性
def test_index_matches_files(rules):
    idx = json.loads((RULE_DIR / "rules_index.json").read_text(encoding="utf-8"))
    assert idx["total"] == len(rules), "索引 total 与文件数不符"
    idx_ids = {x["id"] for x in idx["rules"]}
    file_ids = {r["id"] for r in rules}
    assert idx_ids == file_ids, f"索引与文件 id 不一致：{idx_ids ^ file_ids}"


def test_index_severity_and_type_consistent(rules):
    idx = json.loads((RULE_DIR / "rules_index.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rules}
    for x in idx["rules"]:
        r = by_id[x["id"]]
        assert x["severity"] == r["severity"], f"{x['id']} 索引 severity 过期"
        assert x["check_type"] == r["check"]["type"], f"{x['id']} 索引 check_type 过期"
        assert x["category"] == r["category"], f"{x['id']} 索引 category 过期"


def test_four_required_scopes_covered(rules):
    """用户指定的四个取数范围必须都有规则。"""
    cats = {r["category"] for r in rules}
    for c in ("安全区域边界-访问控制", "安全区域边界-入侵防范",
              "安全计算环境-网络设备", "安全计算环境-安全设备"):
        assert c in cats, f"缺少类别：{c}"
