"""共有プール（ADR-008）。

テーマ単位の定期収集が貯めたイベントを、ユーザーの関心で**検索なしに**並べ替える。
イベント文書には per-user の推薦スコアを保存せず、読み出し時に §6.8 の決定論的
スコアを付ける。根拠は 1 回の一括取得で引き、一覧の evidencePreview と採点の両方に使う。
"""

from __future__ import annotations

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


def candidates(*, now: datetime) -> list[ApiEvent]:
    """一覧に出してよいプール: 期間内に見た、表示可能で、対象の種別で、まだ終わっていないイベント。"""
    since = now - timedelta(days=settings.pool_window_days)
    return [
        e
        for e in store.list_recent_events(since)
        if e.validation_status in ("verified", "partial")
        and e.kind in SHOWN_KINDS
        and not _finished(e, now)
    ]


def ranked_pool(
    preferences: UserPreferences, *, now: datetime
) -> tuple[list[ApiEvent], dict[str, list[Evidence]]]:
    """プールを関心で採点して並べる。スコアはメモリ上だけで、保存しない。"""
    pool = candidates(now=now)
    evidence_by_id = store.get_evidence_for_events(pool)
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
