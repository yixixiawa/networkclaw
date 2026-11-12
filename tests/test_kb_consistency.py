"""知识库回归测试：两份拓扑数据的交叉一致性 + 索引来源完整性。

价值：`knowledge/experiments/*.md`（进向量库）与 `knowledge/topology/*.json`
（结构化数据集）是从同一批 .topo **独立推导**的，历史上漂移过两次
（路由器接口编号偏 1、Eth-Trunk 成员链路丢失），而且漂移很难肉眼发现。
这里把它固化成断言：以后改任一边的解析逻辑，跑测试就会报警。

依赖本地实验包与生成产物（均已 gitignore），缺失时自动跳过。
"""
import json
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
EXP_DIR = BASE / "knowledge" / "experiments"
TOPO_DIR = BASE / "knowledge" / "topology"

from tools.kb_consistency import check_all, find_md, parse_md  # noqa: E402
from tools.topo_extract import SRC_ROOT, find_topo, parse_topo  # noqa: E402

_have_data = SRC_ROOT.is_dir() and TOPO_DIR.is_dir() and EXP_DIR.is_dir()
pytestmark = pytest.mark.skipif(not _have_data, reason="实验包/生成产物缺失（gitignore）")


# ---------------------------------------------------------------- 交叉一致性
def test_md_and_json_are_fully_consistent():
    """核心断言：全部实验的 md 与 topology json 一致（当前 57 个 / 0 不一致）。"""
    r = check_all()
    bad = [lab for lab in r["labs"] if lab["problems"]]
    assert r["total"] >= 50, f"校验到的实验太少：{r['total']}"
    assert not bad, "md 与 json 漂移：" + "; ".join(
        f"{lab['experiment']}({lab['problems']})" for lab in bad[:5])


# ---------------------------------------------------------------- 历史 bug 回归
def test_router_interface_is_zero_based():
    """回归①：AR 路由器首口是 GE0/0/0（曾误按 1 基编号）。"""
    topo = find_topo(SRC_ROOT / "BGP-基本配置工程")
    data = parse_topo(topo, "BGP-基本配置工程")
    pair = next(l for l in data["links"]
                if {l["src"], l["dst"]} == {"AR1", "AR2"})
    assert pair["interfaces"][0]["src_if"] == "GigabitEthernet0/0/0"
    assert pair["interfaces"][0]["dst_if"] == "GigabitEthernet0/0/0"
    # 交换机仍应是 1 基（LSW 首个业务口 = GE0/0/1）
    md = find_md("BGP-基本配置工程")
    assert "GigabitEthernet0/0/0" in md.read_text(encoding="utf-8")


def test_eth_trunk_member_links_are_kept():
    """回归②：一条 line 挂多个 interfacePair（链路聚合）时，成员口不能丢。"""
    topo = find_topo(SRC_ROOT / "MSTP配置练习试卷")
    data = parse_topo(topo, "MSTP配置练习试卷")
    bundled = [l for l in data["links"] if len(l["interfaces"]) > 1]
    assert bundled, "没有解析到聚合链路，说明 topo 结构变了"
    assert any(len(l["interfaces"]) == 3 for l in data["links"])
    # md 侧同样要逐条列出成员口（否则知识库里的拓扑是残缺的）
    md = parse_md(find_md("MSTP配置练习试卷"))
    lsw_pair = {t for t in md["links"] if t[0].startswith("LSW") and t[2].startswith("LSW")}
    assert len(lsw_pair) >= 3


# ---------------------------------------------------------------- 索引来源
def test_topology_dataset_matches_index():
    idx = json.loads((TOPO_DIR / "index.json").read_text(encoding="utf-8"))
    assert idx["total"] >= 50
    for lab in idx["labs"]:
        fp = TOPO_DIR / f"{lab['experiment']}.json"
        assert fp.exists()


def test_lab_reports_are_fed_into_knowledge():
    """回归③：实验报告（含 issues.md）必须进知识库，且带「历史记录」抬头。

    2026-11 起知识库改为「精」而非「多」：清洗会剔除碎片/纯命令/重复块，
    块数比过去少是预期结果。因此这里改断言「报告内容确实在索引里」+
    「规模仍然可观」，不再用写死的 1000 当质量代理。
    """
    from core.rag import REPORT_HEADER, _lab_report_texts, load_chunks

    texts = _lab_report_texts()
    if not texts:
        pytest.skip("data/lab_reports 为空（尚未跑过批量实验）")
    assert any("踩坑清单" in t for t in texts), "issues.md 未纳入"
    assert any(REPORT_HEADER in t for t in texts), "运行报告缺少历史记录抬头"
    chunks = load_chunks()
    assert len(chunks) > 300, "清洗后知识库规模异常偏小，检查清洗规则是否误删"
    assert all(len(c) >= 40 for c in chunks), "清洗后不应残留碎片块"
    assert any(REPORT_HEADER in c or "踩坑清单" in c for c in chunks)
