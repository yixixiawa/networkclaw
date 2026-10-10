"""启动时自动拓扑巡检：截取 eNSP / 虚拟机窗口 → 本地多模态模型识读 → 快照落盘。

定位：
    用户在前几轮已经可以「手动给一张拓扑图让模型看」，本模块把这件事自动化：
    程序每次启动时自动「看一眼」当前拓扑（eNSP 或虚拟机窗口），把识读结论做成
    快照，供后续所有对话引用（agent 系统提示词注入 + get_topology_snapshot 工具）。

自动化与知情权的平衡（用户明确要求「需要告知用户」）：
    1. 自动执行前**明确播报**：截哪个窗口、图存哪里、用哪个模型、为什么
    2. 截图只落本机 logs/captures/，识读只走本地多模态模型，不上传
    3. 提供三处开关：--no-auto-vision（CLI）、设置对话框（GUI）、/autovision off
    4. 若窗口被遮挡需要置前抓取，会提前说明（可能打扰当前操作）

防抖：
    与上次截图做 OpenCV 差分，画面没变就跳过识图（省下 10~40 秒的推理），
    直接复用上一次的结论，并在日志里说明。
"""
from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

from core import screen_capture
from core.paths import BASE_DIR

SNAPSHOT_JSON = BASE_DIR / "data" / "topology_snapshot.json"
SNAPSHOT_MD = BASE_DIR / "data" / "topology_snapshot.md"

SNAPSHOT_MAX_AGE_H = 12          # 快照视为「新鲜」的小时数
CONTEXT_MAX_CHARS = 1500         # 注入模型上下文的最大长度


# ---------------------------------------------------------------- 告知文案

def notice(keyword: str | None = None) -> str:
    """启动时的告知文本：本功能会做什么、数据去哪、怎么关。"""
    ok, why = screen_capture.available()
    if not ok:
        return f"[自动拓扑巡检] 未启用：{why}"
    target = screen_capture.pick_target(
        (keyword,) if keyword else None)
    lines = [
        "[自动拓扑巡检] 已开启，即将自动执行一次：",
        f"  · 目标窗口：{('「' + target['title'] + '」') if target else '（未找到 eNSP / 虚拟机窗口，将跳过）'}",
        "  · 截图只保存在本机 logs/captures/，不上传；识读由本地多模态模型完成",
        "  · 识读结论会存到 data/topology_snapshot.md，供后续对话引用",
        "  · 若窗口被遮挡，可能需要短暂把它切到前台（不影响窗口内容）",
        "  · 关闭方式：启动时加 --no-auto-vision，或对话中 /autovision off（GUI 在设置里）",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- 快照读写

def load_snapshot() -> dict | None:
    """读取上次巡检快照（无 / 损坏时返回 None）"""
    if not SNAPSHOT_JSON.exists():
        return None
    try:
        data = json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _save_snapshot(result: dict) -> None:
    """巡检结论落盘：JSON（机器读）+ Markdown（人读）"""
    try:
        SNAPSHOT_JSON.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        head = (f"# 当前拓扑快照\n\n"
                f"- 采集时间：{result.get('time', '')}\n"
                f"- 来源窗口：{result.get('window', '')}\n"
                f"- 截图：{result.get('image', '')}\n"
                f"- 模型：{result.get('model', '')}\n\n"
                f"## 模型识读结论\n\n{result.get('description', '').strip()}\n")
        SNAPSHOT_MD.write_text(head, encoding="utf-8")
    except OSError:
        pass


def snapshot_age_h(snapshot: dict | None = None) -> float | None:
    """快照距今多少小时（无时间戳返回 None）"""
    snap = snapshot or load_snapshot()
    if not snap or not snap.get("time"):
        return None
    try:
        t = datetime.datetime.strptime(snap["time"], "%Y-%m-%d %H:%M:%S")
        return (datetime.datetime.now() - t).total_seconds() / 3600
    except ValueError:
        return None


def snapshot_fresh(max_age_h: float = SNAPSHOT_MAX_AGE_H, snapshot: dict | None = None) -> bool:
    age = snapshot_age_h(snapshot)
    return age is not None and age <= max_age_h


def context_for_model(max_chars: int = CONTEXT_MAX_CHARS) -> str:
    """把快照结论做成可拼进系统提示词的段落（不新鲜/为空时返回空串）"""
    snap = load_snapshot()
    if not snap or not snapshot_fresh(snapshot=snap):
        return ""
    desc = (snap.get("description") or "").strip()
    if not desc:
        return ""
    if len(desc) > max_chars:
        desc = desc[:max_chars] + "…（已截断，完整内容见 data/topology_snapshot.md）"
    return (f"\n\n【当前拓扑快照（{snap.get('time', '')} 由自动巡检采集，来源："
            f"{snap.get('window', '未知窗口')}）】\n{desc}\n"
            f"（引用以上信息时请注明来自自动巡检；若用户表示拓扑已变化，"
            f"可调用 capture_topology 工具重新查看）")


# ---------------------------------------------------------------- 巡检执行

def auto_inspect(keyword: str | None = None, provider=None, force: bool = False,
                 show_thinking: bool = False,
                 on_think=None, on_answer=None) -> dict:
    """执行一次自动巡检（阻塞；GUI 请放线程里跑）。

    流程：截图（OpenCV 预处理 + 差分）→ 按需跳过 → 本地多模态识读 → 落盘快照。

    Args:
        keyword: 目标窗口关键字（如 "vmware"）；None 用默认关键字表
        provider: 识图用的提供方；None 自动选可看图的（一般是本地模型）
        force: True 时无视差分直接重新识图
        show_thinking: 打印/回调模型思考过程
        on_think / on_answer: 流式回调（GUI 打字机用）

    Returns:
        {ok, action, image, window, changed, description, summary, message, model}
        action ∈ captured / skipped-unchanged / skipped-novision / failed
    """
    started = time.time()
    result: dict = {"ok": False, "action": "failed", "image": None, "window": "",
                    "changed": 1.0, "description": "", "summary": "",
                    "message": "", "model": "", "time": ""}

    # 1) 截图
    cap = screen_capture.capture(keyword)
    if not cap["ok"]:
        result["message"] = cap["message"]
        return result
    result["image"] = str(cap["image"])
    result["window"] = cap["window"]["title"]
    result["changed"] = cap.get("changed", 1.0)

    # 2) 画面没变 + 已有新鲜快照 → 跳过识图，复用结论
    prev = load_snapshot()
    if (not force and prev and prev.get("description")
            and snapshot_fresh(snapshot=prev)
            and cap.get("changed", 1.0) < screen_capture.CHANGED_RATIO):
        result.update({
            "ok": True, "action": "skipped-unchanged",
            "description": prev["description"], "model": prev.get("model", ""),
            "time": prev.get("time", ""),
            "message": (f"画面与上次一致（差异 {cap['changed'] * 100:.2f}%），"
                        f"复用 {prev.get('time', '')} 的识读结论，未重新推理"),
        })
        return result

    # 3) 本地多模态识读
    from core.providers import vision_capable

    prov = provider
    if isinstance(prov, str):
        from core.providers import get_provider

        prov = get_provider(prov)
    if prov is None:
        prov = vision_capable()
    if prov is None:
        result["message"] = ("没有可用的视觉提供方（需要本地 llama-server + mmproj）。"
                             "截图已保存：" + str(cap["image"]))
        return result
    result["model"] = prov.name

    from core.vision import describe_image

    description = describe_image(str(cap["image"]), question="",
                                 provider=prov, show_thinking=show_thinking,
                                 on_think=on_think, on_answer=on_answer)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result.update({
        "ok": True, "action": "captured", "description": description,
        "time": now,
        "summary": _first_lines(description, 3),
        "message": (f"已截取「{cap['window']['title']}」并由 {prov.name} 完成识读"
                    f"（{time.time() - started:.0f}s）"),
    })
    _save_snapshot(result)
    return result


def _first_lines(text: str, n: int = 3) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[:n])


def render_result(result: dict) -> str:
    """把巡检结果渲染成给用户看的文本"""
    head = {
        "captured": "✅ 自动拓扑巡检完成",
        "skipped-unchanged": "⏭️ 自动拓扑巡检：画面无变化，复用上次结论",
        "skipped-novision": "⚠️ 自动拓扑巡检：识图能力不可用",
        "failed": "⚠️ 自动拓扑巡检未成功",
    }.get(result.get("action", ""), "自动拓扑巡检")
    lines = [head]
    if result.get("message"):
        lines.append(result["message"])
    if result.get("image"):
        lines.append(f"截图：{result['image']}")
    if result.get("description"):
        lines.append("")
        lines.append(result["description"])
    return "\n".join(lines)
