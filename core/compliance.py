"""等保2.0 规则引擎：加载 dengbao_rules、对配置文本求值、遍历设备实连拉取配置。

规则只有两类机器可判（与生成器三道自检一致）：
- config_regex：pattern 在配置里匹配不到 → 不合格（pattern 支持负向先行断言
  表达「应存在某段且其中不得含某模式」，不要用 ^ 做跨行锚点）
- manual_confirm：机器判不了 → 只计数提醒，不算漏洞，不进红色气泡

设备大类映射：switch/router → 规则的 network_device；firewall → firewall；
规则里的 ips/apt 不适用于普通数通设备，自动跳过。

拉取配置走 device_conn 直连（只读 display current-configuration），不走 MCP
工具——避免 21 台设备的全文配置逐条写进会话历史，且绕开回显截断。
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from core.paths import BASE_DIR

RULES_DIR = BASE_DIR / "knowledge" / "compliance" / "dengbao_rules"

CONFIG_COMMANDS = {
    "huawei": "display current-configuration",
    "cisco": "show running-config",
    "ruijie": "show running-config",
}


def load_rules(rules_dir: Path | None = None) -> list[dict]:
    """读全部规则 YAML。坏了的单条跳过并记录（规则库不能因为一条坏文件全灭）。"""
    import yaml

    d = Path(rules_dir or RULES_DIR)
    rules: list[dict] = []
    for f in sorted(d.glob("*.yaml")):
        try:
            r = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(r, dict) and r.get("id"):
            r["_file"] = f.name
            rules.append(r)
    return rules


def _rule_kinds(rule: dict) -> set[str]:
    """规则适用的设备大类集合（把规则的 device_type 展开成本地 kind）。"""
    dt = (rule.get("device_type") or "").strip().lower()
    if dt == "network_device":
        return {"switch", "router"}
    return {dt} if dt else set()


def rules_for(rules: list[dict], kind: str) -> list[dict]:
    """按设备大类过滤规则；unknown 大类不套规则（宁漏勿误报）。"""
    return [r for r in rules if kind in _rule_kinds(r)]


def evaluate(config_text: str, rules: list[dict]) -> dict:
    """对一份配置求值。返回 {failures, passed, manual}。

    failure: {id, control_point, requirement, severity, remediation,
              evidence_hint, expect}
    """
    failures: list[dict] = []
    passed = 0
    manual = 0
    text = config_text or ""
    for r in rules:
        chk = r.get("check") or {}
        ctype = chk.get("type")
        if ctype == "manual_confirm":
            manual += 1
            continue
        if ctype != "config_regex":
            manual += 1  # 未知类型按需人工确认处理，绝不误报成漏洞
            continue
        try:
            hit = re.search(chk.get("pattern", ""), text) is not None
        except re.error:
            manual += 1
            continue
        if hit:
            passed += 1
        else:
            failures.append({
                "id": r.get("id", ""),
                "control_point": r.get("control_point", ""),
                "requirement": r.get("requirement", ""),
                "severity": r.get("severity", "medium"),
                "remediation": r.get("remediation") or [],
                "evidence_hint": r.get("evidence_hint", ""),
                "expect": chk.get("expect", ""),
            })
    # 高危在前，同严重度按规则号排序（气泡和详情面板展示顺序稳定）
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    failures.sort(key=lambda f: (sev_rank.get(f["severity"], 3), f["id"]))
    return {"failures": failures, "passed": passed, "manual": manual}


# ---------------------------------------------------------------- 实连拉取

def _vendor_of(dev: dict) -> str:
    return (dev.get("vendor") or "huawei").strip().lower() or "huawei"


def collect_config(dev: dict, timeout: float = 25.0) -> str:
    """登录单台设备拉运行配置（只读 display/show，不下发任何配置命令）。"""
    from core import device_conn

    cmd = CONFIG_COMMANDS.get(_vendor_of(dev), CONFIG_COMMANDS["huawei"])
    if dev.get("transport") == "serial":
        sess = device_conn.open_serial(
            dev.get("serial_port", ""), timeout=timeout, disable_paging=True)
    else:
        sess = device_conn.open_telnet(
            dev.get("host", ""), port=int(dev.get("port", 0) or 0),
            timeout=timeout, disable_paging=True)
    try:
        return sess.exec_command(cmd, timeout=timeout) or ""
    finally:
        try:
            sess.close()
        except Exception:  # noqa: BLE001
            pass


def scan_devices(devices: list[dict], rules: list[dict] | None = None,
                 workers: int = 6, timeout: float = 25.0) -> dict:
    """遍历设备拉配置 + 求值。返回 {results, errors, generated}。

    results 每条：{key, name, model, kind, high, medium, low, manual,
                   failures, passed, error}
    单台失败不影响整体（error 记原因）；没有型号的设备 kind=unknown 跳过求值。
    """
    from core.topology_model import classify

    rules = rules if rules is not None else load_rules()
    results: list[dict] = []
    errors: list[str] = []

    def _one(dev: dict) -> dict:
        key = (f"{dev.get('host')}:{dev.get('port')}" if dev.get("host")
               else dev.get("serial_port") or dev.get("key") or "")
        kind = classify(dev.get("model") or "", dev.get("name") or "")
        out = {"key": key, "name": dev.get("name") or key,
               "model": dev.get("model") or "未知型号", "kind": kind,
               "high": 0, "medium": 0, "low": 0, "manual": 0, "passed": 0,
               "failures": [], "error": ""}
        if kind == "unknown":
            out["error"] = "无法识别设备大类（无型号），跳过规则求值"
            return out
        mine = rules_for(rules, kind)
        if not mine:
            out["error"] = f"没有适用于 {kind} 的规则"
            return out
        try:
            cfg = collect_config(dev, timeout=timeout)
        except Exception as e:  # noqa: BLE001  单台失败不拖垮整体
            out["error"] = f"{type(e).__name__}: {e}"[:120]
            return out
        if not cfg.strip():
            out["error"] = "配置拉取为空（登录失败或回显异常）"
            return out
        rep = evaluate(cfg, mine)
        out.update(failures=rep["failures"], passed=rep["passed"],
                   manual=rep["manual"],
                   high=sum(1 for f in rep["failures"] if f["severity"] == "high"),
                   medium=sum(1 for f in rep["failures"] if f["severity"] == "medium"),
                   low=sum(1 for f in rep["failures"] if f["severity"] == "low"))
        return out

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(_one, d): d for d in devices}
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001
                d = futs[fut]
                errors.append(f"{d.get('name') or d.get('key')}: {e}")

    import time

    results.sort(key=lambda r: (-r["high"], r["name"]))
    return {"results": results, "errors": errors,
            "generated": time.strftime("%Y-%m-%d %H:%M:%S")}
