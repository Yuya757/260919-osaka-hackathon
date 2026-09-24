"""主催者投稿の管理コマンド（ADR-009）。認証が無い間、管理者が手で使う。

    FIRESTORE_ENABLED=true GCP_PROJECT_ID=osaka-hackathon-260919 \\
    PYTHONPATH=src python -m event_agent.entrypoints.admin confirm <postId>
    ... pin <postId> --until 2026-10-15     # PR 枠（JST のその日の終わりまで）
    ... unpin <postId> / hide <postId> / show <postId> / metrics <postId>
    ... purge-grounding --dry-run | --apply  # 検索グラウンディング由来のデータを消す（ADR-014）

ローカルからは Application Default Credentials で Firestore に書く。Cloud Run Job
から実行するなら
``gcloud run jobs execute event-agent-daily --tasks=1 --args="-m,event_agent.entrypoints.admin,confirm,<postId>"``。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta, timezone

from event_agent.workflows import purge
from event_agent.workflows.organizer_posts import (
    PostNotFound,
    confirm_post,
    hide_post,
    pin_post,
    post_metrics,
    show_post,
    unpin_post,
)

JST = timezone(timedelta(hours=9))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="event_agent.entrypoints.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("confirm", "unpin", "hide", "show", "metrics"):
        sub.add_parser(name).add_argument("post_id")
    pin = sub.add_parser("pin")
    pin.add_argument("post_id")
    pin.add_argument("--until", required=True, help="YYYY-MM-DD（JST のその日の終わりまで固定）")
    purge_cmd = sub.add_parser("purge-grounding")
    mode = purge_cmd.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="件数だけを出す")
    mode.add_argument("--apply", action="store_true", help="実際に消す")
    return parser


def _purge_grounding(apply: bool) -> int:
    plan = purge.plan_purge()
    summary = plan.summary()
    if apply:
        purge.apply_purge(plan)
    print(json.dumps({"applied": apply, **summary}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = datetime.now(timezone.utc)
    if args.command == "purge-grounding":
        return _purge_grounding(args.apply)
    try:
        if args.command == "confirm":
            result = confirm_post(args.post_id, now=now)
        elif args.command == "pin":
            until = datetime.combine(date.fromisoformat(args.until), time(23, 59, 59), tzinfo=JST)
            result = pin_post(args.post_id, until=until, now=now)
        elif args.command == "unpin":
            result = unpin_post(args.post_id, now=now)
        elif args.command == "hide":
            result = hide_post(args.post_id, now=now)
        elif args.command == "show":
            result = show_post(args.post_id, now=now)
        else:
            result = post_metrics(args.post_id)
    except PostNotFound:
        print(f"投稿が見つかりません: {args.post_id}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result.model_dump(by_alias=True, mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
