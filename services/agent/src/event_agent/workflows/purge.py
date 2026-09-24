"""検索グラウンディング由来のデータを共有プールから消す（ADR-014）。

Grounding with Google Search の結果は、データベースを作るのに使えず、プロンプトを
送った本人にしか見せられない。以前の定期収集と手動 Run は、検索結果のリンク先を
読んでイベントにし、全員に見せていたので、それで作ったものを消す。

消すもの:

- イベント: 検索テーマ（``source == "search"``）で集めたもの、または ``themeId`` が
  無く、収集元が公開 API（Doorkeeper・jGrants）でないもの（手動・チャットの Run）
- それらの Run と根拠（``agentRuns/{runId}`` と ``evidence``）。残すイベントが指す Run は残す
- それらのボット投稿（``dedupKey`` で決まる）と主催者の申請（``eventClaims``）
- 主催者投稿は消さない。消すイベントに結び付いていれば、結び付きだけ外す

利用者が登録したページ（``user-registered`` / ``watched-pages``）と API 由来は残す。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from event_agent.extraction.post_text import post_id_for
from event_agent.schemas import ApiEvent
from event_agent.storage.store import store
from event_agent.workflows.pool import invalidate_pool_cache
from event_agent.workflows.themes import theme_by_id

API_SOURCES = frozenset({"Doorkeeper", "jGrants（デジタル庁）"})


@dataclass
class PurgePlan:
    event_keys: list[str] = field(default_factory=list)
    organizer_edited: int = 0
    run_ids: list[str] = field(default_factory=list)
    bot_post_ids: list[str] = field(default_factory=list)
    unlink_post_ids: list[str] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)
    by_theme: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict[str, object]:
        return {
            "events": len(self.event_keys),
            "eventsEditedByOrganizer": self.organizer_edited,
            "runs": len(self.run_ids),
            "botPosts": len(self.bot_post_ids),
            "organizerPostsToUnlink": len(self.unlink_post_ids),
            "claims": len(self.claim_ids),
            "eventsByTheme": dict(sorted(self.by_theme.items())),
        }


def is_grounding_derived(event: ApiEvent) -> bool:
    if event.theme_id is None:
        return event.source not in API_SOURCES
    try:
        return theme_by_id(event.theme_id).source == "search"
    except ValueError:
        # user-registered など、テーマ表に無いものは消さない
        return False


def plan_purge() -> PurgePlan:
    events = store.list_all_events()
    doomed = [e for e in events if is_grounding_derived(e)]
    kept_runs = {e.source_run_id for e in events if not is_grounding_derived(e)}

    plan = PurgePlan()
    plan.event_keys = [e.dedup_key for e in doomed]
    plan.organizer_edited = sum(1 for e in doomed if e.organizer_edit is not None)
    plan.run_ids = sorted({e.source_run_id for e in doomed} - kept_runs)
    for event in doomed:
        theme = event.theme_id or "(テーマなし)"
        plan.by_theme[theme] = plan.by_theme.get(theme, 0) + 1

    doomed_ids = {e.event_id for e in doomed}
    doomed_keys = set(plan.event_keys)
    wanted_bot_ids = {post_id_for("bot", key) for key in doomed_keys}
    for post in store.list_organizer_posts():
        if post.origin == "bot":
            if post.post_id in wanted_bot_ids or post.linked_dedup_key in doomed_keys:
                plan.bot_post_ids.append(post.post_id)
        elif post.linked_event_id in doomed_ids or post.linked_dedup_key in doomed_keys:
            plan.unlink_post_ids.append(post.post_id)
    plan.claim_ids = [c.claim_id for c in store.list_claims() if c.event_id in doomed_ids]
    return plan


def apply_purge(plan: PurgePlan) -> None:
    for post_id in plan.unlink_post_ids:
        post = store.get_organizer_post(post_id)
        if post is not None:
            store.save_organizer_post(
                post.model_copy(update={"linked_event_id": None, "linked_dedup_key": None})
            )
    store.delete_organizer_posts(plan.bot_post_ids)
    store.delete_claims(plan.claim_ids)
    store.delete_events(plan.event_keys)
    store.delete_runs(plan.run_ids)
    invalidate_pool_cache()
