"""单个 eNSP 实验的端到端驱动：起设备 → 本地模型配置 → 逐台验收 → 记录问题。

这一层是「用模型跑实验」的主体，刻意把三个阶段分开：

    ① 起设备（GUI）：eNSP 打开拓扑 → Ctrl+A 全选 → 点「开启设备」→ 等 Telnet 端口
    ② 模型配置（Telnet + MCP）：把题目要求与设备连接参数交给本地 Qwen，
       让它自己通过 exec_telnet_command 下发配置，并自行 display 验证
    ③ 验收（Telnet 直连）：对每台设备取 display current-configuration，
       与实验包自带参考答案（.model 提取）逐行比对，算出命中率与缺失项

参考答案**只在阶段③使用**，阶段②不喂给模型——否则它只是抄答案，看不出真实水平。

产物：
    data/run_logs/<日期>/<NN-实验名>.jsonl         模型每次调用与每条下发命令
    data/run_logs/<日期>/<NN-实验名>.events.jsonl  设备探测/验收事件
    data/lab_reports/<NN-实验名>.md                人读的实验报告（含问题清单）

用法：
    python tools/lab_run_agent.py 01
    python tools/lab_run_agent.py 01 --rounds 30 --no-up   # 设备已起，跳过阶段①
"""
from __future__ import annotations

import argparse
import asyncio
import builtins
import dataclasses
import functools
import os
import re
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# 长任务要脱离终端跑，stdout 重定向到文件时是块缓冲，日志会「看起来卡住」。
# 这里把本模块的 print 全部改成行缓冲，排查时才能实时看到进度。
print = functools.partial(builtins.print, flush=True)  # noqa: A001

from core import run_log  # noqa: E402
from core.device_conn import TelnetSession, probe_tcp  # noqa: E402

HOST = os.environ.get("LAB_HOST", "192.168.10.130")
DOC_DIR = BASE_DIR / "knowledge" / "experiments"
REPORT_DIR = BASE_DIR / "data" / "lab_reports"

# 参考答案里的「设备默认配置」，不计入验收比对
NOISE_PATTERNS = (
    "cluster enable", "ntdp enable", "ndp enable", "drop illegal-mac alarm",
    "diffserv domain default", "drop-profile default", "undo info-center enable",
    "authentication-scheme default", "authorization-scheme default",
    "accounting-scheme default", "domain default", "domain default_admin",
    "local-user admin", "user-interface con 0", "user-interface vty 0 4",
    "return", "header shell", "stelnet server enable", "telnet server enable",
)
# 以这些前缀开头的是噪声（单纯进入某个视图，不带配置）
NOISE_PREFIX = ("interface ", "aaa", "#", "quit", "vlan 1")

# 单次生成上限。本地 9B 约 2.3 t/s，400 token ≈ 3 分钟；
# 不设上限模型会一路写到上下文耗尽（实测第一轮就写了上千字还不收口）。
# 上限既要压住"模型写长篇规划"，又不能小到把工具调用的 JSON 参数截断——
# 实测 400 会切掉 create_device_manual 的参数，llama-server 直接回 500，
# 整个实验归零。512 是实测能容纳一次 telnet 工具调用的稳妥值。
MAX_TOKENS = int(os.environ.get("LAB_MAX_TOKENS", "512"))


# ---------------------------------------------------------------- 实验文档解析

def doc_path(num: str) -> Path:
    hits = sorted(DOC_DIR.glob(f"{num}-*.md"))
    if not hits:
        raise SystemExit(f"没有实验 {num} 的文档（{DOC_DIR}）")
    return hits[0]


def parse_doc(num: str) -> dict:
    """把实验文档拆成 题目 / 设备 / 链路 / 参考答案 四块。"""
    text = doc_path(num).read_text(encoding="utf-8")
    name = text.splitlines()[0].lstrip("# ").strip() if text else num

    def section(title: str) -> str:
        m = re.search(rf"^## .*{title}.*?$(.*?)(?=^## |\Z)", text,
                      re.M | re.S)
        return (m.group(1) if m else "").strip()

    devices: list[dict] = []
    for line in section("设备清单").splitlines():
        m = re.match(r"^\|\s*([A-Za-z0-9_-]+)\s*\|\s*([^|]+?)\s*\|\s*(\d+|-)\s*\|", line)
        if not m:
            continue
        nm, model, port = m.group(1), m.group(2).strip(), m.group(3)
        if port.isdigit():
            devices.append({"name": nm, "model": model, "port": int(port)})

    ref: dict[str, list[str]] = {}
    cur = ""
    for line in section("参考答案").splitlines():
        m = re.match(r"^###\s+(\S+)", line)
        if m:
            cur = m.group(1)
            ref[cur] = []
            continue
        if cur and line.strip() and not line.startswith("```") and not line.startswith(">"):
            ref[cur].append(line.strip())

    fp = doc_path(num)
    return {
        "num": num, "name": name,
        "stem": fp.stem,          # 形如 01-ACCESS、TRUNK、HYBRID配置练习
        "requirement": section("题目要求"),
        "devices": devices,
        "links": section("链路连接"),
        "notes": section("拓扑图上的文字标注"),
        "reference": ref,
    }


def key_commands(lines: list[str]) -> list[str]:
    """从参考答案里挑出「真正要求下发的配置」，过滤设备默认配置。"""
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        low = s.lower()
        if any(p in low for p in NOISE_PATTERNS):
            continue
        if low.startswith(NOISE_PREFIX):
            continue
        if len(s) < 4:            # 纯数字、单个词之类的片段
            continue
        out.append(s)
    return out


# ---------------------------------------------------------------- 设备探测

def probe_devices(devices: list[dict], host: str = HOST) -> list[dict]:
    """逐台 Telnet 登录并取版本/初始配置，确定「设备到底起来没有」。"""
    rows = []
    for d in devices:
        row = dict(d)
        row["reachable"] = False
        row["detail"] = ""
        p = probe_tcp(host, d["port"], timeout=3)
        if not p.get("ok"):
            row["detail"] = f"端口未开放（{p.get('error', '')}）"
            run_log.event("device_probe", name=d["name"], port=d["port"], ok=False,
                          detail=row["detail"])
            rows.append(row)
            continue
        for attempt in (1, 2, 3):
            s = TelnetSession(host, d["port"], timeout=25)
            try:
                s.login()
                s.prepare()
                out = s.exec_command("display version", timeout=30)
                row["reachable"] = True
                row["detail"] = " / ".join(out.strip().splitlines()[:3])[:200]
                break
            except Exception as e:  # noqa: BLE001
                row["detail"] = f"{type(e).__name__}: {e}"[:200]
                if attempt < 3:
                    time.sleep(8)
            finally:
                try:
                    s.close()
                except Exception:  # noqa: BLE001
                    pass
        run_log.event("device_probe", name=d["name"], port=d["port"],
                      model=d["model"], ok=row["reachable"], detail=row["detail"])
        rows.append(row)
    return rows


def device_config(name: str, port: int, host: str = HOST,
                  cmd: str = "display current-configuration") -> str:
    """取一台设备的当前配置（验收用，直连不走模型）。"""
    s = TelnetSession(host, port, timeout=30)
    try:
        s.login()
        s.prepare()
        return s.exec_command(cmd, timeout=90)
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass


def snapshot(doc: dict, host: str = HOST) -> dict[str, str]:
    """配置前的配置快照。

    必须拍这一张：很多实验包在设备里**预置了参考答案**（vrpcfg.zip / .model），
    开机就已经是配好的状态。不拍 before 的话验收会 100% 命中，
    看起来「模型全对」，其实它一条命令都没下发成功。
    """
    out: dict[str, str] = {}
    for d in doc["devices"]:
        try:
            out[d["name"]] = device_config(d["name"], d["port"], host=host)
        except Exception as e:  # noqa: BLE001
            out[d["name"]] = ""
            run_log.event("snapshot_fail", name=d["name"], port=d["port"],
                          error=f"{type(e).__name__}: {e}"[:160])
    return out


# ---------------------------------------------------------------- 模型配置阶段

LAB_SYSTEM = """你是 NetworkClaw 网络运维助手，正在 eNSP 模拟器里完成一个离线实验。

【环境事实（不要臆造，也不要向用户索取）】
- 目标主机与端口已在任务书里给出，每台设备一个 Telnet 端口，直接连接即可；
- eNSP 模拟器里的设备**通常没有用户名/密码**，username/password 留空；
- 这是与生产网隔离的实验拓扑，配置类命令**不需要再征求用户同意**，
  请直接带 confirm=true 下发。

【undo 只在「清理接口旧配置」时用，其余高危命令仍禁用】
- 华为交换机改接口类型时，若接口上已有 trunk/hybrid 配置，设备会回
  `Error: Please renew the default configuration`，**必须先清理**：
  `interface X;undo port link-type;port link-type access;port default vlan 10`
  实验模式下 `undo` 已被放行（需 confirm=true），可以放心用。
- 仍然**硬拦、不要碰**：shutdown / delete / reset / reboot / reload /
  save / write / erase / format。这些用了整条命令会被拒绝。
- 不要为了"保险"把 undo 堆在每条命令前面——只在设备明确报
  "Please renew the default configuration" 时才清理。

【改接口类型的清理顺序（华为 S 系列，顺序错了会一直报错）】
从 trunk/hybrid 改成 access，必须**先撤属性、再改类型**：
  interface GigabitEthernet0/0/1;
  undo port trunk allow-pass vlan 10 20 30;
  undo port trunk pvid vlan;
  port link-type access;
  port default vlan 10
即 `allow-pass` → `pvid` → `link-type`，顺序颠倒设备会一直回
`Error: Please renew the default configuration`。
同一处连续两次失败就换思路（例如保留 trunk 只调整 allow-pass 列表），
不要原地重发第三次。

【回显解读（误读会导致空转）】
- 返回以 `[已执行]` 开头 = 命令**已成功下发**，不要当成失败；
- 回显末尾若有「⚠ 设备报错」提示，那才是真正失败，必须据此改命令；
- `[已拦截]` = 被安全策略拒绝（shutdown/save/reset 等），换做法，不要重试。

【工具使用硬性要求（否则配置一定失败）】
- 每次 exec_telnet_command 都是**新建 Telnet 会话**，视图状态不会保留。
  因此同一视图下的多条命令必须用英文分号 `;` 串成一次调用，例如：
  exec_telnet_command(command="system-view;sysname LSW1;vlan batch 10 20", confirm=true)
- 进入接口后继续配置同理：
  command="interface GigabitEthernet0/0/1;port link-type trunk;port trunk allow-pass vlan 10 20"
- 需要回退到用户视图时，在串接末尾加 `return` 或 `quit`。
- 每次下发后用 display 类只读命令验证（display 不需要 confirm），例如
  display vlan / display port vlan / display ip interface brief / display current-configuration | include xxx。
- 配置前可先 display 现状，避免重复配置。

【效率要求（本地模型生成约 2 字/秒，务必精简）】
- **回答必须极简**：每轮只写一句话说明接下来做什么（20 字以内），然后立刻调用工具。
  严禁写长篇规划、推理过程、原理讲解——那会把每轮拖到几分钟。
- **同一台设备的完整配置合并成一次调用**：把 system-view / vlan batch /
  多个 interface 视图下的配置用 `;` 串起来一次下发，不要一条命令发一次。
- 目标节奏：每台设备 1~2 次配置调用 + 1 次 display 验证，整个实验 10 次调用以内。
- 最终总结不超过 200 字。
- **某台设备连续两次失败就先跳过去配下一台**，别在同一处打转——
  轮次耗尽就什么都没配成；没做到的写在最后的总结里。

【工作方式】
1. 先通读题目要求与设备清单，规划每台设备要下什么；
2. 逐台配置，每下发一批就用 display 验证；
3. 全部完成后，用一段简短总结给出每台设备的配置与验证结论；
4. 遇到不确定的命令，用 query_command_template / search_knowledge 查证，不要凭记忆编造。
"""


def build_task(doc: dict, host: str = HOST, ports_note: str = "") -> str:
    lines = [
        f"# 实验 {doc['num']}：{doc['name']}",
        "",
        "## 一、题目要求",
        doc["requirement"] or "（文档中没有单独列出题目要求，请按拓扑标注与设备清单推断）",
        "",
        "## 二、设备与连接方式",
        f"- 所有设备都通过 Telnet 访问，主机：{host}",
        "- 端口映射如下（设备名 -> 端口）：",
    ]
    for d in doc["devices"]:
        lines.append(f"  - {d['name']}（{d['model']}）-> 端口 {d['port']}")
    if ports_note:
        lines.append(f"- 备注：{ports_note}")
    lines += [
        "",
        "## 三、链路连接",
        doc["links"] or "（无）",
        "",
        "## 四、拓扑图上的文字标注",
        doc["notes"] or "（无）",
        "",
        "## 五、你的任务",
        "1. 按题目要求完成所有设备的配置（接口类型、VLAN、IP、路由等）；",
        "2. 每一批配置下发后都要用 display 命令验证；",
        "3. 完成后输出一段总结：每台设备做了什么、验证结果如何、还有什么没做到。",
        "",
        "现在开始。请先用 display 类命令查看设备现状，再动手配置。",
    ]
    return "\n".join(lines)


async def model_configure(doc: dict, devices: list[dict], host: str = HOST,
                          rounds: int = 40, ctx_note: str = "") -> dict:
    """让本地 Qwen 通过 MCP 工具配置整个实验，返回过程记录。"""
    # 实验模式：撤销前缀 undo 从「硬拦」降级为「需确认」。
    # 不改的话，改接口类型前必须先 undo，设备只回 "Please renew the default
    # configuration"，模型会在同一条命令上无限重试（实测 8 轮原地打转）。
    # 必须在**拉起 MCP 服务端之前**设置——服务端是独立子进程，靠环境变量继承。
    os.environ["NETWORKCLAW_LAB_MODE"] = "1"

    from mcp_tools.client import McpHub

    from core.agent import run_agent
    from core.providers import get_provider

    prov = get_provider("local")
    # Qwen3.5-9B 在这个任务上必须三重约束，否则跑不完一个实验：
    #   ① enable_thinking=False：思考链会疯狂打转并吃掉上下文；
    #   ② max_tokens 硬上限：不设的话它会一路生成到 32K 上下文满，
    #      按 2.3 t/s 算要三个多小时，且中途不调用任何工具；
    #   ③ 提示词里要求极简输出（见 LAB_SYSTEM）。
    prov = dataclasses.replace(
        prov,
        extra_body={**(prov.extra_body or {}),
                    "max_tokens": MAX_TOKENS,
                    "chat_template_kwargs": {"enable_thinking": False}},
    )

    # 只挂知识库与 Telnet 两个服务端。
    # 之前还挂了 device-manual（create_device_manual / update_...），结果模型
    # 把轮次全花在"给设备建手册"上，一条配置都没下发——工具越多 9B 模型越容易跑偏。
    servers = {
        "knowledge": str(BASE_DIR / "mcp_tools" / "template_server.py"),
        "device-telnet": str(BASE_DIR / "mcp_tools" / "telnet_server.py"),
    }
    steps: list[dict] = []
    t0 = time.time()
    answer = ""
    async with McpHub(servers) as hub:
        print(f"[模型] 已接入 {len(hub.tools)} 个工具："
              f"{', '.join(sorted({t['name'] for t in hub.tools}))[:200]}")
        # 单轮 LLM 报错（典型是 llama-server 解析工具参数失败回 500）不该让
        # 整个实验归零——整场重来一遍代价是十几分钟。失败就换个更保守的轮次重试。
        last_err = ""
        for attempt in (1, 2, 3):
            try:
                answer = await run_agent(
                    build_task(doc, host=host, ports_note=ctx_note),
                    hub, max_rounds=rounds, show_thinking=False, provider=prov,
                    system_prompt=LAB_SYSTEM,
                    on_step=lambda s: steps.append(s),
                )
                last_err = ""
                break
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"[:300]
                print(f"[模型配置] 第 {attempt} 次失败：{last_err[:200]}")
                if attempt < 3:
                    steps.clear()
                    await asyncio.sleep(5)
        if last_err:
            print("[模型配置] 三次均失败，本实验按未配置处理")
    return {
        "answer": answer,
        "steps": steps,
        "elapsed": round(time.time() - t0, 1),
        "tool_calls": len(steps),
    }


# ---------------------------------------------------------------- 验收

def _hit(flat_cfg: str, keys: list[str]) -> tuple[int, list[str]]:
    hit, missing = 0, []
    for k in keys:
        if re.sub(r"\s+", " ", k) in flat_cfg:
            hit += 1
        else:
            missing.append(k)
    return hit, missing


def verify(doc: dict, host: str = HOST, before: dict[str, str] | None = None) -> list[dict]:
    """逐台比对：参考答案里的关键配置行，是否出现在设备 running-config 里。

    同时算「配置前的命中数」——设备预置了答案时，净提升（hit - hit_before）
    才代表模型的真实贡献。
    """
    rows = []
    for d in doc["devices"]:
        keys = key_commands(doc["reference"].get(d["name"], []))
        row = {"name": d["name"], "port": d["port"], "model": d["model"],
               "expected": keys, "missing": [], "hit": 0, "total": len(keys),
               "hit_before": 0, "net": 0, "config": "", "error": ""}
        if not keys:
            rows.append(row)
            continue
        try:
            cfg = device_config(d["name"], d["port"], host=host)
        except Exception as e:  # noqa: BLE001
            row["error"] = f"{type(e).__name__}: {e}"[:200]
            row["missing"] = keys
            rows.append(row)
            continue
        row["config"] = cfg
        flat = re.sub(r"\s+", " ", cfg)
        row["hit"], row["missing"] = _hit(flat, keys)
        if before and before.get(d["name"]):
            row["hit_before"], _ = _hit(re.sub(r"\s+", " ", before[d["name"]]), keys)
        row["net"] = row["hit"] - row["hit_before"]
        pct = round(row["hit"] * 100 / max(1, row["total"]), 1)
        run_log.event("verify", name=d["name"], port=d["port"],
                      hit=row["hit"], total=row["total"], pct=pct,
                      hit_before=row["hit_before"], net=row["net"],
                      missing=row["missing"])
        rows.append(row)
    return rows


# ---------------------------------------------------------------- 报告

def write_report(doc: dict, probe_rows: list[dict], model_out: dict,
                 verify_rows: list[dict], up_log: str = "") -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    fp = REPORT_DIR / f"{doc.get('stem') or doc['num']}.md"
    lines = [
        f"# {doc['name']}",
        "",
        f"- 实验编号：{doc['num']}",
        f"- 主机：{HOST}",
        f"- 模型耗时：{model_out.get('elapsed', 0)}s ｜ 工具调用：{model_out.get('tool_calls', 0)} 次",
        "",
        "## 一、题目要求",
        doc["requirement"] or "（无）",
        "",
        "## 二、设备情况",
        "| 设备 | 型号 | 端口 | 可达 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for r in probe_rows:
        lines.append(f"| {r['name']} | {r['model']} | {r['port']} | "
                     f"{'✅' if r['reachable'] else '❌'} | {r['detail'][:120]} |")

    lines += ["", "## 三、模型配置结论", "",
              (model_out.get("answer") or "（模型未给出结论）").strip()[:4000]]

    lines += ["", "## 四、验收比对（参考答案 vs 设备实际配置）", "",
              "| 设备 | 命中/应配 | 命中率 | 配置前命中 | 净提升 | 缺失配置 |",
              "|---|---|---|---|---|---|"]
    for r in verify_rows:
        if not r["total"]:
            lines.append(f"| {r['name']} | - | - | - | - | 参考答案未提取到关键配置 |")
            continue
        pct = round(r["hit"] * 100 / max(1, r["total"]), 1)
        miss = "；".join(r["missing"][:8]) or "无"
        lines.append(f"| {r['name']} | {r['hit']}/{r['total']} | {pct}% | "
                     f"{r['hit_before']} | {r['net']:+d} | {miss} |")
    preset = [r for r in verify_rows
              if r["total"] and r["hit_before"] >= r["total"] and r["net"] == 0]
    if preset:
        lines += ["",
                  f"> ⚠️ 设备开机即已自带参考答案配置（{len(preset)} 台："
                  f"{'、'.join(r['name'] for r in preset)}），"
                  "「净提升 0」不代表模型做对了，只能说明模型没有把配置改坏。",
                  ""]

    issues = []
    for r in probe_rows:
        if not r["reachable"]:
            issues.append(f"设备 {r['name']}（端口 {r['port']}）不可达：{r['detail']}")
    for r in verify_rows:
        if r["error"]:
            issues.append(f"设备 {r['name']} 取配置失败：{r['error']}")
        for m in r["missing"]:
            issues.append(f"设备 {r['name']} 缺少配置：{m}")

    lines += ["", "## 五、问题清单", ""]
    lines += [f"{i}. {t}" for i, t in enumerate(issues, 1)] or ["（无）"]
    if up_log:
        lines += ["", "## 六、起设备过程日志", "", "```", up_log[:3000], "```"]
    fp.write_text("\n".join(lines), encoding="utf-8")
    return fp


# ---------------------------------------------------------------- 主流程

async def run_lab(num: str, host: str = HOST, rounds: int = 40,
                  do_up: bool = True, wait: int = 900) -> dict:
    doc = parse_doc(num)
    print(f"### 实验 {num}：{doc['name']}")
    run_log.set_session(f"{num}-{doc['name'].split('：')[-1]}")
    run_log.event("lab_start", num=num, name=doc["name"], host=host,
                  devices=[d["name"] for d in doc["devices"]])

    up_log = ""
    if do_up:
        from tools.lab_up import up as lab_up_sync

        import io
        import contextlib

        # 不能只 redirect 到 StringIO：起设备要跑好几分钟（关 eNSP→拉起→开拓扑→
        # 全选→开设备→等 Telnet 端口），中间输出全被吞掉会让日志"看起来卡死"，
        # 排查时根本分不清是挂了还是在工作。所以边收集边透传真实 stdout。
        class _Tee:
            def __init__(self, *streams):
                self.streams = streams

            def write(self, s):
                for st in self.streams:
                    try:
                        st.write(s)
                    except Exception:  # noqa: BLE001
                        pass

            def flush(self):
                for st in self.streams:
                    try:
                        st.flush()
                    except Exception:  # noqa: BLE001
                        pass

        real_out = sys.stdout
        buf = io.StringIO()
        with contextlib.redirect_stdout(_Tee(buf, real_out)):
            lab_up_sync(num, fresh=True, wait=wait)
        up_log = buf.getvalue()

    print("[设备探测]")
    probe_rows = probe_devices(doc["devices"], host=host)
    for r in probe_rows:
        print(f"  {r['name']:6} {r['model']:8} :{r['port']}  "
              f"{'OK' if r['reachable'] else 'FAIL'}  {r['detail'][:90]}")
    ready = [r for r in probe_rows if r["reachable"]]
    if not ready:
        run_log.event("lab_abort", num=num, reason="没有可达设备")
        return {"num": num, "name": doc["name"], "ok": False,
                "reason": "没有可达设备", "probe": probe_rows}

    print("[配置前快照] 记录设备初始配置（很多实验开机就自带答案，不记会误判）")
    before = snapshot(doc, host=host)
    for name, cfg in before.items():
        print(f"  {name:6} {len(cfg):5} 字符 {'(空/失败)' if not cfg else ''}")

    print(f"[模型配置] 交给本地 Qwen，最多 {rounds} 轮 …")
    try:
        model_out = await model_configure(doc, ready, host=host, rounds=rounds)
    except Exception as e:  # noqa: BLE001
        model_out = {"answer": "", "steps": [], "elapsed": 0, "tool_calls": 0,
                     "error": f"{type(e).__name__}: {e}"}
        print(f"[模型配置] 失败：{e}")
    print(f"[模型配置] 完成：{model_out.get('tool_calls', 0)} 次工具调用，"
          f"{model_out.get('elapsed', 0)}s")

    print("[验收比对]")
    verify_rows = verify(doc, host=host, before=before)
    for r in verify_rows:
        if r["total"]:
            print(f"  {r['name']:6} {r['hit']}/{r['total']}  "
                  f"(配置前 {r['hit_before']}，净 {r['net']:+d})  缺失 {len(r['missing'])} 项")

    fp = write_report(doc, probe_rows, model_out, verify_rows, up_log)
    run_log.event("lab_done", num=num, name=doc["name"], report=str(fp))
    print(f"[报告] {fp}")
    return {"num": num, "name": doc["name"], "ok": True, "report": str(fp),
            "probe": probe_rows, "verify": verify_rows, "model": model_out}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="用本地模型跑一个 eNSP 实验")
    ap.add_argument("num", help="实验编号，如 01")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--rounds", type=int, default=40)
    ap.add_argument("--wait", type=int, default=300)
    ap.add_argument("--no-up", action="store_true", help="设备已起，跳过起设备阶段")
    args = ap.parse_args(argv[1:])

    res = asyncio.run(run_lab(args.num, host=args.host, rounds=args.rounds,
                              do_up=not args.no_up, wait=args.wait))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
