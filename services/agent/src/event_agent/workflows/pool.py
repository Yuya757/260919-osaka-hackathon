"""共有プール（ADR-008）。

テーマ単位の定期収集が貯めたイベントを、ユーザーの関心で**検索なしに**並べ替える。
イベント文書には per-user の推薦スコアを保存せず、読み出し時に §6.8 の決定論的
スコアを付ける。根拠は 1 回の一括取得で引き、一覧の evidencePreview と採点の両方に使う。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from event_agent.config import settings
from event_agent.domain.ranking import score_recommendation
from event_agent.schemas import ApiEvent, Evidence, Recommendation, UserPreferences
from event_agent.storage.store import store


# 一覧に出す種別。補助金などは収集を止めても過去の分がプールに残るため、読み出しでも絞る
# （themes.PAUSED_THEMES と対）
SHOWN_KINDS = ("hackathon", "contest", "meetup")


def _finished(event: ApiEvent, now: datetime) -> bool:
    # 実施日が無い告知（ビジコン・補助金）は締切で判断する
    end = event.dates.event_end or event.dates.event_start or event.dates.application_deadline
    return end < now if end else False


# プールと根拠の読み出しは、一覧を開くたびに数百件の文書を読むので重い。収集は
# 1 日 1 回なので、短い時間だけメモリに持つ。最新の収集時刻が変われば読み直す
_cache: tuple[tuple[int, datetime | None], float, list[ApiEvent], dict[str, list[Evidence]]] | None = None


def invalidate_pool_cache() -> None:
    """主催者の編集などで、プールのイベントが収集以外で変わったときに呼ぶ。"""
    global _cache
    _cache = None


def _recent_with_evidence(now: datetime) -> tuple[list[ApiEvent], dict[str, list[Evidence]]]:
    global _cache
    ttl = settings.pool_cache_seconds
    key = (id(store), store.latest_collection_at())
    clock = time.monotonic()
    if ttl > 0 and _cache and _cache[0] == key and clock - _cache[1] < ttl:
        return _cache[2], _cache[3]
    since = now - timedelta(days=settings.pool_window_days)
    events = [
        e
        for e in store.list_recent_events(since)
        if e.validation_status in ("verified", "partial") and e.kind in SHOWN_KINDS
    ]
    evidence = store.get_evidence_for_events(events)
    if ttl > 0:
        _cache = (key, clock, events, evidence)
    return events, evidence


def candidates(*, now: datetime) -> list[ApiEvent]:
    """一覧に出してよいプール: 期間内に見た、表示可能で、対象の種別で、まだ終わっていないイベント。"""
    events, _ = _recent_with_evidence(now)
    return [e for e in events if not _finished(e, now)]


def ranked_pool(
    preferences: UserPreferences, *, now: datetime
) -> tuple[list[ApiEvent], dict[str, list[Evidence]]]:
    """プールを関心で採点して並べる。スコアはメモリ上だけで、保存しない。"""
    recent, all_evidence = _recent_with_evidence(now)
    pool = [e for e in recent if not _finished(e, now)]
    evidence_by_id = {e.event_id: all_evidence.get(e.event_id, []) for e in pool}
    scored = [
        e.model_copy(
            update={
                "recommendation": Recommendation(
                    score=score_recommendation(
                        e, evidence_by_id.get(e.event_id, []), preferences, now=now
                    ),
                    reason=e.recommendation.reason if e.recommendation else "",
                )
            }
        )
        for e in pool
    ]
    # 両バックエンドで順序が一致するよう、同点は eventId で決める（display_order と同じ規則）
    scored.sort(key=lambda e: (-(e.recommendation.score if e.recommendation else 0), e.event_id))
    return scored, evidence_by_id
