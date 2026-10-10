"""tools/topo_extract.py：.topo 解析与拓扑数据集完整性。

测试依赖本地实验包（data/ensp_labs/ 已 gitignore，仅在实验机上存在），
缺失时自动跳过而不是失败。
"""
import json
from pathlib import Path

import pytest

from tools.topo_extract import parse_topo

BASE = Path(__file__).resolve().parent.parent
BGP_TOPO = BASE / "data" / "ensp_labs" / "src" / "BGP-基本配置工程" / "paper" / "paper.topo"

pytestmark = pytest.mark.skipif(not BGP_TOPO.exists(), reason="本地实验包缺失（gitignore）")


def test_parse_bgp_topology():
    """BGP-基本配置工程：3 台 AR2220 串联（console 2000/2001/2002）+ 2 台 PC。"""
    data = parse_topo(BGP_TOPO, "BGP-基本配置工程")
    assert data["device_count"] == 3
    assert data["pc_count"] == 2
    assert data["link_count"] == 4
    ports = {d.get("console_port") for d in data["devices"]}
    assert ports == {2000, 2001, 2002}
    names = {d["name"] for d in data["devices"]}
    assert {"AR1", "AR2", "AR3"} <= names
    # UUID -> 设备名映射：lab_answers 提取与验收都依赖它
    ids = {d["id"] for d in data["devices"]}
    assert "011A1AB5-C312-4667-B850-C2E48F3E8DFB" in ids      # AR1
    # 画布标注里应有题面网段
    assert any("10.10.23.0/24" in a for a in data["annotations"])
    # AR 路由器做接口名换算（已核实 index i -> GE0/0/i）
    link = data["links"][0]
    assert link["interfaces"][0]["src_if"].startswith("GigabitEthernet0/0/")


def test_topology_dataset_generated_and_consistent():
    idx_fp = BASE / "knowledge" / "topology" / "index.json"
    if not idx_fp.exists():
        pytest.skip("拓扑数据集尚未生成（python tools/topo_extract.py）")
    idx = json.loads(idx_fp.read_text(encoding="utf-8"))
    assert idx["total"] >= 50
    assert len(idx["labs"]) == idx["total"]
    for lab in idx["labs"]:
        fp = BASE / "knowledge" / "topology" / f"{lab['experiment']}.json"
        assert fp.exists(), f"索引里有但文件缺失：{fp.name}"
        d = json.loads(fp.read_text(encoding="utf-8"))
        assert d["device_count"] == lab["devices"]
        assert d["link_count"] == lab["links"]


def test_lab_answers_index_shape():
    idx_fp = BASE / "data" / "lab_answers" / "index.json"
    if not idx_fp.exists():
        pytest.skip("参考答案尚未提取（python tools/extract_answers.py）")
    idx = json.loads(idx_fp.read_text(encoding="utf-8"))
    assert idx["total_labs"] >= 30
    for lab in idx["labs"]:
        for item in lab["devices"]:
            assert item["kind"] in {"answer", "orig", "flash(binary)", "archive", "error"}
