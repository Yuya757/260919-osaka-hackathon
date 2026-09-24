"""Cloud Run Job entrypoint for the daily collection (§14 Phase 2 / ADR-008).

Deployed as the Cloud Run Job ``event-agent-daily`` with 4 tasks run one at a
time (``--tasks 4 --parallelism 1``); each task takes one theme from
``CLOUD_RUN_TASK_INDEX``. Sequential so that a page found by two themes is
extracted once and skipped by the second (決定4). Without the env var (local
run) every theme runs in order.

Run locally with:

    PYTHONPATH=src python -m event_agent.entrypoints.job            # all themes
    PYTHONPATH=src python -m event_agent.entrypoints.job hackathon-kansai
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from event_agent.workflows.collect import run_theme_collection
from event_agent.workflows.themes import (
    COLLECTION_THEMES,
    CollectionTheme,
    theme_by_id,
    theme_for_task_index,
)

logger = logging.getLogger(__name__)


async def collect_theme(theme: CollectionTheme) -> int:
    """Return a process exit code. 0 covers both collecting and skipping."""
    if theme.source == "watched":
        # 利用者が登録したページの見守り（ADR-014）。検索はしない
        from event_agent.workflows.watched_pages import watch_all

        changed, unchanged, started = await watch_all()
        logger.info(
            "watched pages: re-read %s, unchanged %s (started=%s)", changed, unchanged, started
        )
        return 0
    run, started = await run_theme_collection(theme)
    if not started:
        # 今日の分は別の実行が既に担当している。再試行でもここに来る（§9.3）。
        logger.info("run %s already owns today's schedule for %s", run.run_id, theme.id)
        return 0
    logger.info(
        "theme %s run %s finished with status %s (grounding %s, model %s, skipped %s)",
        theme.id, run.run_id, run.status, run.grounding_calls, run.model_calls,
        run.skipped_known_count,
    )
    return 0 if run.status in ("succeeded", "partial_success") else 1


def select_themes(argv: list[str], env: dict[str, str]) -> list[CollectionTheme]:
    if len(argv) > 1:
        return [theme_by_id(argv[1])]
    index = env.get("CLOUD_RUN_TASK_INDEX")
    if index is not None:
        return [theme_for_task_index(int(index))]
    return list(COLLECTION_THEMES)


async def collect_all(themes: list[CollectionTheme]) -> int:
    codes = [await collect_theme(theme) for theme in themes]
    return max(codes) if codes else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(collect_all(select_themes(sys.argv, dict(os.environ))))


if __name__ == "__main__":
    sys.exit(main())
