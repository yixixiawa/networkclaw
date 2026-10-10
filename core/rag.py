"""RAG 流程层：知识库切分写入 + 检索问答（流式输出）。

职责：
- 加载知识文档并切分写入向量库。索引来源共四类：
  ① knowledge/huawei_devices_introduce.txt（设备知识）
  ② knowledge/experiments/*.md（eNSP 实验：题目 + 拓扑 + 参考答案 + 验收要点）
  ③ skills/*/SKILL.md（运行期自建的设备手册）
  ④ data/lab_reports/*.md（实验运行报告 + issues.md 踩坑清单 —— 经验反哺）
- 提供检索（retrieve）与流式问答（ask）：实时打印模型思考过程与回答 token，
  并统计输出 token 数
- 生成走 llama-server，检索向量化走 Ollama

集合隔离：
- 本模块只操作 KNOWLEDGE_COLLECTION（知识库）这一个集合，且通过
  ollama_interface.get_collection(...) 现取句柄，不持有长生命周期集合对象；
- 命令模板检索在 core/template_search.py，操作 TEMPLATE_COLLECTION，两者
  索引指纹各自记录（data/index_state.json），互不干扰；
- 重建知识库索引不会影响命令模板集合，反之亦然。

运行方式：
    python -m core.rag              # 交互式问答
    python -m core.rag --rebuild    # 强制重建知识库索引
"""
import argparse
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.llm_client import print_stats, stream_chat
from core.ollama_interface import (
    BASE_DIR,
    KNOWLEDGE_COLLECTION,
    check_embedder,
    compute_fingerprint,
    get_collection,
    index_is_fresh,
    reset_collection,
    save_index_state,
)

KNOWLEDGE_FILE = BASE_DIR / "knowledge" / "huawei_devices_introduce.txt"
SKILLS_DIR = BASE_DIR / "skills"          # 运行期自建的设备手册（skills/<设备名>/SKILL.md）
EXPERIMENTS_DIR = BASE_DIR / "knowledge" / "experiments"   # eNSP 实验集（tools/ensp_lab_index.py 生成）
LAB_REPORTS_DIR = BASE_DIR / "data" / "lab_reports"        # 批量实验报告 + issues.md（踩坑清单）
RUN_LOGS_DIR = BASE_DIR / "data" / "run_logs"              # 逐轮工具调用与设备回显（JSONL）
TOPOLOGY_DIR = BASE_DIR / "knowledge" / "topology"         # 结构化拓扑数据集（设备/链路/标注）

# 运行报告是「某一次运行的事实」，可能被后续修复推翻——注入时统一加抬头，
# 让模型知道这是历史记录而不是现行规则（issues.md 除外，它是维护中的问题清单）。
REPORT_HEADER = "【历史运行记录（可能已过时，以实验文档与参考答案为准）】"

# ------------------------------------------------------------------ 知识分级
#
# 知识库里的内容可信度并不相同：实验文档是「现行规则」，运行日志是「某一次
# 的事实」。混在一起后模型无法区分"应该怎么做"和"上次是怎么做的"，可能把
# 一次偶发失败当成普遍规律。因此每个来源都打一个 tier 标签，注入时随正文
# 一起进入 prompt，让模型自己掌握取舍尺度。
#
#     rule     现行规则/权威参考：实验文档、设备手册、参考答案
#     history  历史运行记录：实验报告、踩坑清单、运行日志摘要（可能已过时）
#     instance 实例数据：设备介绍、拓扑数据集（事实描述，非操作建议）
TIER_RULE = "rule"
TIER_HISTORY = "history"
TIER_INSTANCE = "instance"

_TIER_PREFIX = {
    TIER_RULE: "【现行规则｜可据此直接作答】",
    TIER_HISTORY: "【历史记录｜仅供参考，与规则冲突时以规则为准】",
    TIER_INSTANCE: "【实例数据｜事实描述，不含操作建议】",
}


def _decorate(text: str, tier: str) -> str:
    """给一段知识正文加可信度前缀（分级标注，随块一起进向量库）。"""
    prefix = _TIER_PREFIX.get(tier, "")
    return f"{prefix}\n{text}" if prefix else text


# ------------------------------------------------------------------ 检索状态
#
# status 取值（调用方据此决定如何向模型交代）：
#     ok            正常命中
#     empty         索引为空（尚未构建 / 被清空）
#     no_match      索引非空，但该问题没有相关片段
#     unavailable   取不到集合句柄（向量库损坏 / 路径不可写）
#     embed_failed  Embedding 服务不可用（Ollama 没跑 / 模型没拉）
#
# 只有 ok 之外的**后两种**属于故障；empty / no_match 是正常结论。
DEGRADED_STATUSES = ("unavailable", "embed_failed")


@dataclass
class RetrievalResult:
    """带状态的检索结果。

    chunks 非空即视为命中；否则看 status 判断是「正常无内容」还是「检索降级」。
    degraded = 检索链路故障（知识库没发挥作用），与「确实没查到」不是一回事。
    """

    chunks: list[str] = field(default_factory=list)
    status: str = "ok"
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok" and bool(self.chunks)

    @property
    def degraded(self) -> bool:
        return self.status in DEGRADED_STATUSES

    def notice(self) -> str:
        """给模型/用户看的一句话说明（ok 时为空串）。"""
        if self.ok:
            return ""
        if self.degraded:
            return (f"⚠ 知识库检索不可用（{self.status}）：{self.reason}。"
                    f"本轮回答**没有**任何知识库依据，请明确告知用户「检索失败、"
                    f"以下内容仅凭模型自身知识」，不要声称查过知识库。")
        if self.status == "empty":
            return f"（知识库为空：{self.reason}。本次未检索到任何片段。）"
        return f"（知识库中没有找到与该问题相关的片段：{self.reason}）"


def _experiment_texts() -> list[str]:
    """eNSP 实验文档：题目 + 拓扑 + 参考答案，让模型配置实验时能"抄"到正确思路。

    文档由 tools/ensp_lab_index.py 从虚拟机实验包解析生成，
    每个实验一个 .md（00-总览.md 是索引，跳过以免噪声）。
    """
    out: list[str] = []
    if not EXPERIMENTS_DIR.is_dir():
        return out
    for p in sorted(EXPERIMENTS_DIR.glob("*.md")):
        if p.name.startswith("00-"):
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if body:
            out.append(f"【eNSP 实验 {p.stem}】\n{body}")
    return out


def _manual_texts() -> list[str]:
    """运行期自建的设备手册：一并切进知识库，让模型「熟悉」自己积累的设备知识"""
    out: list[str] = []
    if not SKILLS_DIR.is_dir():
        return out
    for p in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        try:
            body = p.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if body:
            out.append(f"【设备手册 {p.parent.name}】\n{body}")
    return out


def _lab_report_texts() -> list[str]:
    """批量实验的运行报告 + 踩坑清单（经验反哺）。

    为什么进知识库：模型每次跑同类实验都会重新踩一遍同样的坑
    （视图丢失、undo 被拦、命令报错要换写法……）。把「上一次的实际过程与结论」
    检索回来，能让它复用已修好的做法，而不是从零试错。

    分级：
        issues.md    维护中的问题清单（现象/根因/处置/状态）—— 按现行规则使用
        NN-实验名.md 单次运行记录 —— 一律加「历史运行记录」抬头
    """
    out: list[str] = []
    if not LAB_REPORTS_DIR.is_dir():
        return out
    issues = LAB_REPORTS_DIR / "issues.md"
    if issues.is_file():
        body = issues.read_text(encoding="utf-8", errors="replace").strip()
        if body:
            out.append(f"【eNSP 实验踩坑清单（维护中）】\n{body}")
    for p in sorted(LAB_REPORTS_DIR.glob("*.md")):
        if p.name == "issues.md":
            continue
        body = p.read_text(encoding="utf-8", errors="replace").strip()
        if body:
            out.append(f"{REPORT_HEADER}\n【eNSP 实验运行报告 {p.stem}】\n{body}")
    return out


def _run_log_digests(limit_sessions: int = 40) -> list[str]:
    """把逐轮运行日志压成「一次实验一摘要」，作为第五数据源。

    为什么不是直接把 JSONL 塞进向量库：
        run_logs 里每行都带完整的工具回显（一次 display 可能上千字），直接切块
        会瞬间淹没其它来源——用户问「BGP 邻居起不来怎么办」时，检索到的大概率是
        某次无关实验的 `display current-configuration` 全文。因此这里只提取
        **结构化的结论**：做过哪些实验、命中率多少、哪些设备探测失败、下发过
        哪些配置类命令、有无报错回显。

    行数上限：
        单会话取前 N 个 tool_step 与末尾若干条，避免超长会话把摘要撑爆。

    读取方式：
        复用 core.run_log 的 read_session/list_sessions，不自己拼路径——
        会话名做过安全化处理（`_safe`），直接按文件名猜会漏掉含中文/顿号的实验名。
    """
    try:
        from core import run_log
    except Exception:
        return []

    days = sorted((p.name for p in RUN_LOGS_DIR.iterdir() if p.is_dir()), reverse=True)
    if not days:
        return []

    out: list[str] = []
    for day in days[:3]:                       # 只取最近 3 天
        try:
            sessions = run_log.list_sessions(day)
        except Exception:
            continue
        for tag in sessions[:limit_sessions]:
            try:
                rows = run_log.read_session(day, tag)
            except Exception:
                continue
            digest = _digest_session(day, tag, rows)
            if digest:
                out.append(digest)
    return out


def _digest_session(day: str, tag: str, rows: list[dict], max_steps: int = 12) -> str:
    """把单个会话的 JSONL 行压成一段可检索的摘要文本。"""
    if not rows:
        return ""

    calls = [r for r in rows if r.get("kind") == "llm_call"]
    steps = [r for r in rows if r.get("kind") == "tool_step"]
    if not steps:
        return ""

    models = sorted({c.get("model", "") for c in calls if c.get("model")})
    # 命令去重且保持出现顺序：同一个 display 反复执行只留一次
    seen: dict[str, int] = {}
    for s in steps:
        cmd = str((s.get("args") or {}).get("command", "")).strip()
        if cmd:
            seen[cmd] = seen.get(cmd, 0) + 1

    conf_cmds = [c for c in seen if not c.lower().startswith(("display", "show", "ping", "tracert", "dir", "more"))]
    err_lines = []
    for s in steps:
        out_text = str(s.get("output", ""))
        for kw in ("Error", "Unrecognized", "Wrong parameter", "失败", "不可达"):
            if kw in out_text:
                err_lines.append(f"    - {kw}: {out_text[:120].replace(chr(10), ' ')}")
                break
        if len(err_lines) >= 5:
            break

    parts = [
        f"【运行日志摘要 {day} / {tag}】",
        f"模型：{'/'.join(models) or '未知'}；LLM 调用 {len(calls)} 次，工具下发 {len(steps)} 次。",
    ]
    if conf_cmds:
        parts.append(f"下发过的配置类命令（首次出现的写法）：{'；'.join(conf_cmds[:max_steps])}")
    else:
        parts.append("本次会话只做只读查看，没有下发配置类命令。")
    if err_lines:
        parts.append("出现过的报错回显：\n" + "\n".join(err_lines))
    return "\n".join(parts)


def load_chunks() -> list[str]:
    """读取知识文档 + eNSP 实验集 + 设备手册 + 实验运行报告 + 运行日志摘要，切分为文本块"""
    with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
        raw_text = f.read()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=50,
        separators=["\n\n", "\n", "。", "，", " "]
    )
    chunks = splitter.split_text(_decorate(raw_text, TIER_INSTANCE))
    for text in _experiment_texts():
        chunks += splitter.split_text(_decorate(text, TIER_RULE))
    for text in _manual_texts():
        chunks += splitter.split_text(_decorate(text, TIER_RULE))
    for text in _lab_report_texts():
        chunks += splitter.split_text(_decorate(text, TIER_HISTORY))
    for text in _run_log_digests():
        chunks += splitter.split_text(_decorate(text, TIER_HISTORY))
    return chunks


def knowledge_sources() -> str:
    """索引来源的可读描述（写入 data/index_state.json，便于追溯）。"""
    return (f"{KNOWLEDGE_FILE.name}[instance] + knowledge/experiments/*.md[rule] + "
            f"skills/*/SKILL.md[rule] + data/lab_reports/*.md[history] + "
            f"data/run_logs/**/*.jsonl[history]")


def build_index(force: bool = False) -> int:
    """把知识文档切分后写入知识库集合，返回文本块数量。

    以「内容指纹 + 块数」判断是否需要重建：
    - 一致 → 跳过（幂等，可在每次启动时放心调用）
    - 不一致或 force=True → 仅重建知识库集合（不触碰命令模板集合）

    注意：改完 knowledge/ 里的文档后无需手动清理，指纹变化会自动触发重建。
    """
    chunks = load_chunks()
    fingerprint = compute_fingerprint(chunks)

    if not force and index_is_fresh(KNOWLEDGE_COLLECTION, fingerprint, len(chunks)):
        print(f"知识库索引已是最新（{len(chunks)} 个文本块），跳过重建")
        return len(chunks)

    check_embedder()  # 先预检：重建是「先删后建」，Embedding 不可用时不能动旧索引
    coll = reset_collection(KNOWLEDGE_COLLECTION)
    coll.add(
        documents=chunks,
        ids=[f"hw_{i}" for i in range(len(chunks))]
    )
    save_index_state(
        KNOWLEDGE_COLLECTION, fingerprint, len(chunks),
        source=knowledge_sources(),
    )
    print(f"知识库索引已重建：{len(chunks)} 个文本块写入集合 {KNOWLEDGE_COLLECTION}")
    return len(chunks)


def retrieve(query: str, n_results: int = 3) -> list[str]:
    """从知识库集合检索相关片段。

    检索依赖 Ollama 的 Embedding 服务，而它不一定在跑（尤其在交付给别人的机器上）。
    因此这里把「取不到片段」统一降级为返回空列表 + 一条可读提示：
    对话仍可继续（由模型自身知识回答），而不是整轮问答直接失败。

    注意：需要区分降级原因时请用 `retrieve_ex()`——本函数保留为兼容接口，
    只返回片段列表（旧调用方无需改动）。
    """
    return retrieve_ex(query, n_results).chunks


def retrieve_ex(query: str, n_results: int = 3) -> RetrievalResult:
    """检索并返回**带状态**的结果（推荐入口）。

    为什么要返回状态而不是裸列表：
        裸列表无法区分「索引本来就是空的」「问题确实没有匹配」与
        「Embedding 服务挂了导致检索失败」这三种情况。前两种是正常结论，
        第三种是**故障**——但两者在调用方看来都是 []，模型于是会把「检索失败」
        当成「知识库中没有相关内容」照常作答，给出看似合理、实则未经验证的答案。
        返回值里带上 status 后，调用方（ask / search_knowledge）就能把降级
        明确写进 prompt，让模型知道自己是在「没有弹药」的情况下发言。
    """
    try:
        coll = get_collection(KNOWLEDGE_COLLECTION)
        total = coll.count()
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"[警告] 知识库不可用（{msg}），本次跳过检索")
        return RetrievalResult([], "unavailable", msg)

    if total == 0:
        return RetrievalResult([], "empty", "索引为空（尚未构建或集合被清空）")
    n_results = max(1, min(n_results, total))
    try:
        results = coll.query(query_texts=[query], n_results=n_results)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"[警告] 知识库检索失败（Embedding 服务不可用？）：{msg}")
        print("       本次跳过检索，仅依赖模型自身知识回答。"
              "修复方式：启动 Ollama（ollama serve）并拉取模型 ollama pull nomic-embed-text")
        return RetrievalResult([], "embed_failed", msg)
    docs = results["documents"][0]
    if not docs:
        return RetrievalResult([], "no_match", "索引非空，但没有匹配到相关片段")
    return RetrievalResult(docs, "ok", "")


def _build_prompt(query: str, context: str, notice: str = "") -> str:
    """组装 RAG 提示词。

    notice 非空时（检索降级/空库）插在知识片段之前，明确告诉模型
    「你没有拿到依据」——否则空 context 会被模型当成「知识库里确实没有」，
    从而放心地用自身记忆编出看似权威的答案。
    """
    warning = f"\n{notice}\n" if notice else ""
    basis = "以下知识片段" if context else "（本轮没有可用的知识片段）"
    return f"""你是一个华为网络设备专家。请严格根据{basis}回答问题。如果知识片段中没有相关信息，请明确说“知识库中没有找到相关信息”。
{warning}
知识片段：
{context}

用户问题：{query}

回答："""


def ask(query: str, show_thinking: bool = True, stream: bool = True,
        images: list[str] | None = None, provider=None,
        on_think: Callable[[str], None] | None = None,
        on_answer: Callable[[str], None] | None = None) -> str:
    """检索 + 流式 LLM 生成，返回最终回答文本。

    - show_thinking=True 时实时打印模型思考过程
    - stream=True 时逐 token 实时打印回答；stream=False 则只收集不打印，
      由调用方（如 main.py）统一渲染返回值，便于同时记录会话历史。
    - images：随问题一起送入模型的图片路径（拓扑截图等）；需要该提供方支持图片。
    - provider：使用的模型提供方（名称或 Provider），默认当前激活的。
    - on_think / on_answer：流式片段回调（GUI 用）；一旦给出，对应内容就交给回调
      渲染而不再打印到 stdout（桌面端靠它做逐 token 打字机效果）。
    """
    result_ret = retrieve_ex(query)
    retrieved = result_ret.chunks
    if retrieved:
        print(f"检索到 {len(retrieved)} 个相关片段：")
        for i, doc in enumerate(retrieved, 1):
            print(f"  [{i}] {doc[:80]}...")
    elif result_ret.degraded:
        # 故障与「确实没查到」必须区分：前者要提示用户修服务，后者不用
        print(f"[降级] 知识库未能参与本轮回答：{result_ret.status} —— {result_ret.reason}")
    else:
        print("知识库中未检索到相关片段（索引为空或问题不匹配），将仅依赖模型自身知识回答")

    prompt = _build_prompt(query, "\n\n".join(retrieved), result_ret.notice())
    content = prompt
    if images:
        try:
            from core.vision import build_user_content
            content = build_user_content(prompt, images)
        except Exception as e:
            print(f"[警告] 图片读取失败，本次按纯文本提问：{type(e).__name__}: {e}")
            content = prompt

    # 拓扑快照注入：自动巡检的当前拓扑结论作为 system 消息，供回答时参考
    messages: list[dict] = []
    try:
        from core.auto_topology import context_for_model

        ctx = context_for_model(max_chars=800)
        if ctx:
            messages.append({"role": "system", "content": ctx.strip()})
    except Exception:
        pass
    messages.append({"role": "user", "content": content})

    result = stream_chat(
        messages=messages,
        show_thinking=show_thinking,
        show_answer=stream,
        provider=provider,
        on_think=on_think,
        on_answer=on_answer,
    )
    print_stats(result)
    return result.content


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG 知识库问答")
    parser.add_argument("--rebuild", action="store_true", help="强制重建知识库索引")
    args = parser.parse_args()

    build_index(force=args.rebuild)
    while True:
        query = input("\n请输入查询内容（q 退出）：")
        if query.strip().lower() in ("q", "quit", "exit"):
            break
        ask(query)
