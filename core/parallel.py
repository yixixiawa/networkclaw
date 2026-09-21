"""多模态并行编排：本地视觉模型看图 + 云端文本模型推理，多路同时跑，再融合成一份回答。

为什么这么分工：
    本地 Qwen3.5-9B 带 mmproj 能读图，但吞吐受显卡限制；
    DeepSeek 文本推理强、速度快，但 API 是纯文本、不接受图片。
    因此「看图」留在本地（拓扑图含内网 IP/设备名，不外传更安全），
    「推理解答」可以并行交给云端，最后再由一路模型把结果融合。

两种编排策略：
    parallel（默认）  视觉识读与各文本模型同时开跑，最后融合阶段拿到「识图结论 + 各方回答」
    cascade           先识图，再把识图结论喂给各文本模型，回答依据更充分但总耗时更长

用法：
    from core.parallel import run_multimodal_parallel
    report = run_multimodal_parallel("这个拓扑有什么风险", images=[r"topo.png"])
    print(report.render())

命令行：
    python -m core.parallel "给这个拓扑提改进建议" --image topo.png --providers local,deepseek
"""
from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from core.llm_client import ParallelOutcome, chat_once
from core.providers import Provider, configured_providers, get_provider, vision_capable

STRATEGIES = ("parallel", "cascade")

SYNTHESIS_PROMPT = """你是 NetworkClaw 网络运维助手。下面是同一个问题分别交给多个模型得到的回答，
请你综合成一份最终答案。

【用户问题】
{query}

【本地视觉模型对拓扑图的识读结果】
{vision}

【各模型回答】
{answers}

融合要求：
1. 直接给结论，不要出现「模型 A 说、模型 B 说」这类表述；
2. 涉及具体配置命令时以命令模板/知识库中的写法为准，给出可直接粘贴的命令并标明配置视图；
3. 如果视觉识读结果与某个回答矛盾，以视觉识读出的实际拓扑为准，并在答案中说明修正点；
4. 各方都没有把握的地方，明确写「需现场确认」，不要编造；
5. 全文控制在 800 字以内，重点突出、可执行。
"""


@dataclass
class VisionReading:
    """本地视觉模型对图片的识读结果"""

    provider: str = ""
    model: str = ""
    text: str = ""
    error: str = ""
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())


@dataclass
class ParallelReport:
    """一次多模态并行编排的完整产物"""

    query: str
    strategy: str = "parallel"
    images: list[str] = field(default_factory=list)
    vision: VisionReading | None = None
    outcomes: list[ParallelOutcome] = field(default_factory=list)
    synthesis: str = ""
    synth_label: str = ""
    elapsed: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def answers(self) -> list[ParallelOutcome]:
        return [o for o in self.outcomes if o.ok]

    def render(self) -> str:
        """渲染成可直接打印 / 存档的文本"""
        lines = [f"【多模态并行编排】策略={self.strategy} ｜ 总耗时 {self.elapsed}s",
                 f"问题：{self.query}"]
        if self.images:
            lines.append(f"图片：{', '.join(self.images)}")
        for note in self.notes:
            lines.append(f"[提示] {note}")

        if self.vision is not None:
            v = self.vision
            lines += ["", f"———— 视觉识读（{v.provider}/{v.model} ｜ {v.elapsed}s）————"]
            lines.append(v.text.strip() if v.ok else f"[失败] {v.error}")

        for o in self.outcomes:
            lines += ["", f"———— 模型回答（{o.label} ｜ {o.provider}/{o.model or '?'} ｜ {o.elapsed}s）————"]
            if not o.ok:
                lines.append(f"[失败] {o.error}")
                continue
            lines.append((o.result.content or "").strip() or "（无内容）")
            if o.result.usage:
                lines.append(f"[token：输入 {o.result.usage.get('prompt_tokens', '?')} ＋ "
                             f"输出 {o.result.usage.get('completion_tokens', '?')} ＝ "
                             f"{o.result.usage.get('total_tokens', '?')}]")

        if self.synthesis:
            lines += ["", f"———— 融合答案（{self.synth_label}）————", self.synthesis.strip()]
        return "\n".join(lines)


def _resolve_text_providers(providers: list[str] | None) -> list[Provider]:
    """确定要并行提问的文本提供方列表（默认：所有已配置可用的）"""
    if providers:
        out = []
        for name in providers:
            try:
                out.append(get_provider(name))
            except KeyError as e:
                print(f"[警告] {e}")
        return out
    return configured_providers()


def _default_synth_provider(vision_prov: Provider | None,
                            text_providers: list[Provider]) -> Provider:
    """默认由「云端提供方」做融合（吞吐快）；没有云端则用本地"""
    for p in text_providers:
        if p.kind == "cloud":
            return p
    if text_providers:
        return text_providers[0]
    return vision_prov or get_provider()


def run_multimodal_parallel(query: str,
                            images: list[str] | None = None,
                            providers: list[str] | None = None,
                            strategy: str = "parallel",
                            synthesize: bool = True,
                            synth_provider: str | Provider | None = None,
                            show_thinking: bool = False,
                            timeout: int | None = None,
                            on_think: "Callable[[str], None] | None" = None,
                            on_answer: "Callable[[str], None] | None" = None) -> ParallelReport:
    """并行跑多路模型（含视觉），可选融合成一份答案。

    Args:
        query: 用户问题
        images: 需要识读的图片路径（为空则跳过视觉一路，退化为多模型并行对比）
        providers: 参与并行回答的提供方名称列表；默认所有已配置可用的
        strategy: parallel（视觉与文本同跑）| cascade（先识图再喂给各文本模型）
        synthesize: 是否在最后增加一路「融合」调用，把各方结果合成一份最终答案
        synth_provider: 融合用哪个提供方；默认优先云端
        show_thinking: 是否实时打印思考过程（并行时建议关闭，避免输出交错）
        timeout: 覆盖各路的请求超时
        on_think / on_answer: 流式片段回调，**只作用于最后的融合一路**
            （各路的原始回答是并行产出的，实时上屏会互相交错，因此只在融合时用回调）

    Returns:
        ParallelReport：含视觉识读、各方回答、融合答案与耗时
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"未知策略「{strategy}」，可选：{', '.join(STRATEGIES)}")

    started = time.time()
    images = [str(i) for i in (images or []) if i]
    text_providers = _resolve_text_providers(providers)
    vision_prov = vision_capable() if images else None
    report = ParallelReport(query=query, strategy=strategy, images=images)

    if not text_providers and vision_prov is None:
        report.notes.append("没有可用的模型提供方，请先配置 DeepSeek 密钥或启动本地 llama-server")
        report.elapsed = round(time.time() - started, 1)
        return report

    # ---------------------------------------------------------- 视觉识读
    def _read_vision() -> VisionReading | None:
        if vision_prov is None:
            return None
        from core.vision import describe_image  # 延迟导入，避免环状依赖
        t0 = time.time()
        try:
            parts = []
            for img in images:
                parts.append(describe_image(img, question=query, provider=vision_prov).strip())
            return VisionReading(provider=vision_prov.name, model=vision_prov.model,
                                 text="\n\n".join(p for p in parts if p),
                                 elapsed=round(time.time() - t0, 1))
        except Exception as e:
            return VisionReading(provider=vision_prov.name, model=vision_prov.model,
                                 error=f"{type(e).__name__}: {e}",
                                 elapsed=round(time.time() - t0, 1))

    vision_reading: VisionReading | None = None
    if images and vision_prov is None:
        report.notes.append("本轮带图，但没有可用的视觉提供方（需本地多模态模型 + mmproj），已跳过识图")

    # cascade：先识图，再把结论喂给各文本模型
    if images and strategy == "cascade" and vision_prov is not None:
        print(f"[并行编排] cascade：先由 {vision_prov.name} 识图 …")
        vision_reading = _read_vision()
        report.vision = vision_reading

    vision_text = (vision_reading.text if vision_reading and vision_reading.ok else "")

    # ---------------------------------------------------------- 并行提问
    def _ask(prov: Provider) -> ParallelOutcome:
        t0 = time.time()
        prompt = query
        if vision_text:
            prompt = (f"{query}\n\n【当前网络拓扑（由本地视觉模型识读）】\n{vision_text}\n\n"
                      "请结合上面的实际拓扑回答问题。")
        try:
            return chat_once(prompt, provider=prov, timeout=timeout,
                             show_thinking=show_thinking)
        except Exception as e:
            return ParallelOutcome(label=prov.name, provider=prov.name, model=prov.model,
                                   error=f"{type(e).__name__}: {e}",
                                   elapsed=round(time.time() - t0, 1))

    jobs: list[tuple[str, object]] = [("vision", _read_vision)] if (
        images and strategy == "parallel" and vision_prov is not None) else []
    jobs += [(f"text:{p.name}", (lambda p=p: _ask(p))) for p in text_providers]

    if jobs:
        print(f"[并行编排] 同时启动 {len(jobs)} 路：{', '.join(name for name, _ in jobs)}")
        results: dict[str, object] = {}
        with ThreadPoolExecutor(max_workers=min(len(jobs), 6)) as pool:
            futures = {pool.submit(fn): name for name, fn in jobs}
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    results[name] = fut.result()
                except Exception as e:  # 兜底：单路异常不影响整体
                    results[name] = e
                print(f"[并行编排] {name} 完成")

        if "vision" in results and isinstance(results["vision"], VisionReading):
            report.vision = results["vision"]
        for name, value in results.items():
            if name.startswith("text:") and isinstance(value, ParallelOutcome):
                report.outcomes.append(value)
        # 保证展示顺序与请求顺序一致
        order = [p.name for p in text_providers]
        report.outcomes.sort(key=lambda o: order.index(o.provider) if o.provider in order else 99)

    if not report.outcomes and not (report.vision and report.vision.ok):
        report.notes.append("所有并行路径都失败了，请检查提供方配置与网络")
        report.elapsed = round(time.time() - started, 1)
        return report

    # ---------------------------------------------------------- 融合
    if synthesize:
        good = report.answers
        sources = len(good) + (1 if vision_text else 0)
        if sources < 2:
            report.notes.append("只有一路结果，跳过融合（直接采用该路回答）")
        else:
            synth = (get_provider(synth_provider) if synth_provider is not None
                     else _default_synth_provider(vision_prov, text_providers))
            answers_text = "\n\n".join(
                f"--- [{o.label}] {o.provider}/{o.model} ---\n{(o.result.content or '').strip()}"
                for o in good) or "（无）"
            prompt = SYNTHESIS_PROMPT.format(
                query=query,
                vision=vision_text or "（本轮无图片或识图失败）",
                answers=answers_text,
            )
            print(f"[并行编排] 由 {synth.name} 融合 {len(good)} 路回答"
                  f"{' + 视觉识读' if vision_text else ''} …")
            outcome = chat_once(prompt, provider=synth, timeout=timeout or synth.timeout,
                                show_thinking=show_thinking,
                                on_think=on_think, on_answer=on_answer)
            if outcome.ok:
                report.synthesis = outcome.result.content
                report.synth_label = f"{synth.name}/{synth.model}（{outcome.elapsed}s）"
            else:
                report.notes.append(f"融合失败：{outcome.error}（已保留各路原始回答）")

    report.elapsed = round(time.time() - started, 1)
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="多模态并行编排（本地识图 + 多模型并行回答 + 融合）")
    parser.add_argument("query", nargs="+", help="要提问的内容")
    parser.add_argument("--image", action="append", default=[], help="图片路径，可多次指定")
    parser.add_argument("--providers", default=None, help="参与并行的提供方，逗号分隔（默认全部可用）")
    parser.add_argument("--strategy", choices=STRATEGIES, default="parallel")
    parser.add_argument("--no-synth", action="store_true", help="不做融合，只看各路原始回答")
    args = parser.parse_args()

    rpt = run_multimodal_parallel(
        " ".join(args.query),
        images=args.image,
        providers=[s.strip() for s in args.providers.split(",")] if args.providers else None,
        strategy=args.strategy,
        synthesize=not args.no_synth,
    )
    print("\n" + rpt.render())
