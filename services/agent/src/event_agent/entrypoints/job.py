"""Cloud Run Job entrypoint for the daily collection (§14 Phase 2).

Not deployed yet: no Cloud Run Job or Cloud Scheduler exists for it, and
`.github/workflows/deploy-develop.yml` does not build it. It is the caller that
makes the §9.3 scheduled-run lock usable, and it keeps the schedule's entry
point out of the FastAPI service, which serves requests rather than batches.

Run locally with:

    PYTHONPATH=src python -m event_agent.entrypoints.job
"""

from __future__ import annotations

import asyncio
import logging
import sys

from event_agent.schemas import DEMO_USER_ID, UserPreferences
from event_agent.workflows.collect import run_daily_collection

logger = logging.getLogger(__name__)


async def collect_for_user(user_id: str) -> int:
    """Return a process exit code. 0 covers both collecting and skipping."""
    run, started = await run_daily_collection(UserPreferences(), user_id=user_id)
    if not started:
        # 今日の分は別の実行が既に担当している。再試行でもここに来る（§9.3）。
        logger.info("run %s already owns today's schedule for %s", run.run_id, user_id)
        return 0
    logger.info("run %s finished with status %s", run.run_id, run.status)
    return 0 if run.status in ("succeeded", "partial_success") else 1


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    user_id = sys.argv[1] if len(sys.argv) > 1 else DEMO_USER_ID
    return asyncio.run(collect_for_user(user_id))


if __name__ == "__main__":
    raise SystemExit(main())
