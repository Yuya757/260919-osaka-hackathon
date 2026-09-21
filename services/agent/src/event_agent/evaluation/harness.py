"""Drive one evaluation case through the real workflow.

Only the two I/O boundaries are replaced: search results and page bytes. The
URL guard, extraction, validation, dedup and ranking are the production code
paths, so a regression in any of them shows up here.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from event_agent.config import settings
from event_agent.evaluation.cases import EvalCase
from event_agent.page_fetcher import FixturePageSource, PageFetcher, SearchHit
from event_agent.schemas import AgentRun, ApiEvent
from event_agent.store import store
from event_agent.trajectory import ToolTrajectory


class FakeSearch:
    """Stands in for the grounding call, returning the case's hits."""

    def __init__(self, hits: tuple[SearchHit, ...]) -> None:
        self._hits = hits
        self.demo_mode = False  # フィクスチャ経路ではなく本番と同じ分岐を通す

    def reset_call_budget(self) -> None:
        return

    async def search_with_grounding(self, query: str) -> list[dict[str, str]]:
        return [
            {"url": hit.url, "title": hit.title, "excerpt": hit.excerpt}
            for hit in self._hits
        ]

    async def generate_text(self, prompt: str, system: str | None = None) -> str | None:
        return None


@dataclass
class CaseResult:
    case: EvalCase
    run: AgentRun
    events: list[ApiEvent]
    trajectory: ToolTrajectory
    evidence_by_event: dict[str, list] = field(default_factory=dict)


@contextmanager
def _patched(case: EvalCase, trajectory: ToolTrajectory) -> Iterator[None]:
    from event_agent.workflows import collect

    original_gemini = collect.gemini_client
    original_fetcher = collect.page_fetcher
    original_sources = collect.DEMO_PAGE_SOURCES
    collect.gemini_client = FakeSearch(case.search_hits)
    collect.page_fetcher = PageFetcher(FixturePageSource(dict(case.pages)))
    collect.DEMO_PAGE_SOURCES = dict(case.source_types)
    try:
        yield
    finally:
        collect.gemini_client = original_gemini
        collect.page_fetcher = original_fetcher
        collect.DEMO_PAGE_SOURCES = original_sources


@contextmanager
def _settings_for_eval() -> Iterator[None]:
    saved = (settings.demo_catalog_fallback, settings.step_delay_seconds)
    # 評価では抽出結果だけを見る。デモカタログで補うと何を測ったのか分からなくなる。
    settings.demo_catalog_fallback = False
    settings.step_delay_seconds = 0.0
    try:
        yield
    finally:
        settings.demo_catalog_fallback, settings.step_delay_seconds = saved


async def run_case(case: EvalCase) -> CaseResult:
    from event_agent.workflows.collect import run_collect_workflow

    store.reset()
    trajectory = ToolTrajectory()
    with _settings_for_eval(), _patched(case, trajectory):
        run = await run_collect_workflow(
            case.preferences, True, now=case.clock, trajectory=trajectory
        )
    events = store.list_events(run.run_id)
    evidence = {e.event_id: store.get_evidence(e.evidence_ids) for e in events}
    return CaseResult(
        case=case, run=run, events=events, trajectory=trajectory,
        evidence_by_event=evidence,
    )
