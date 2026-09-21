"""Deterministic rules: §6.6 statuses, §6.7 dedup, §6.8 scoring, §7.5 confidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from event_agent.enrichment import (
    derive_validation_status,
    group_duplicates,
    merge_group,
    normalize_title,
    normalize_url,
    score_event,
    score_recommendation,
    title_similarity,
)
from event_agent.schemas import (
    ApiEvent,
    EventDates,
    EventLocation,
    Evidence,
    Recommendation,
    UserPreferences,
)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 21, 9, 0, tzinfo=JST)


def make_event(
    *,
    event_id: str,
    title: str,
    start: datetime,
    official: str,
    region: str | None = "大阪",
    application_url: str | None = None,
    organizer: str | None = "Example",
    deadline: datetime | None = None,
    confidence: float = 0.9,
) -> ApiEvent:
    return ApiEvent(
        eventId=event_id,
        title=title,
        category="hackathon",
        summary="",
        organizer=organizer,
        location=EventLocation(type="offline", venue=region, region=region),
        dates=EventDates(
            applicationDeadline=deadline,
            eventStart=start,
            eventEnd=None,
        ),
        officialUrl=official,
        applicationUrl=application_url,
        confidence=confidence,
        recommendation=Recommendation(score=0, reason=""),
        firstSeenAt=NOW,
        lastSeenAt=NOW,
    )


# ---- §6.6 rejected ----

def test_finished_event_is_rejected() -> None:
    assert (
        derive_validation_status(
            confidence=1.0, threshold=0.8, deadline_known=True,
            has_conflict=False, has_required_evidence=True, is_finished=True,
        )
        == "rejected"
    )


def test_out_of_target_year_is_rejected() -> None:
    assert (
        derive_validation_status(
            confidence=1.0, threshold=0.8, deadline_known=True,
            has_conflict=False, has_required_evidence=True, in_target_year=False,
        )
        == "rejected"
    )


def test_unsafe_url_is_rejected() -> None:
    assert (
        derive_validation_status(
            confidence=1.0, threshold=0.8, deadline_known=True,
            has_conflict=False, has_required_evidence=True, url_safe=False,
        )
        == "rejected"
    )


def test_rejected_beats_quarantined() -> None:
    """終了済みかつ矛盾ありなら rejected が優先される。"""
    assert (
        derive_validation_status(
            confidence=0.1, threshold=0.8, deadline_known=False,
            has_conflict=True, has_required_evidence=False, is_finished=True,
        )
        == "rejected"
    )


def test_defaults_keep_previous_behaviour() -> None:
    assert (
        derive_validation_status(
            confidence=0.95, threshold=0.8, deadline_known=True,
            has_conflict=False, has_required_evidence=True,
        )
        == "verified"
    )


# ---- 画面設計書§8-2 集約サイト単独の下限 ----

def test_aggregator_only_below_the_floor_is_held_back() -> None:
    assert (
        derive_validation_status(
            confidence=0.55, threshold=0.8, deadline_known=True,
            has_conflict=False, has_required_evidence=True,
            aggregator_only=True, aggregator_min_confidence=0.60,
        )
        == "quarantined"
    )


def test_aggregator_only_at_the_floor_is_shown() -> None:
    """0.60 ちょうどは表示する。閾値は「未満を落とす」。"""
    assert (
        derive_validation_status(
            confidence=0.60, threshold=0.8, deadline_known=True,
            has_conflict=False, has_required_evidence=True,
            aggregator_only=True, aggregator_min_confidence=0.60,
        )
        == "partial"
    )


def test_official_source_ignores_the_aggregator_floor() -> None:
    """公式・主催者の根拠があれば、低い信頼度でも partial として出す。"""
    assert (
        derive_validation_status(
            confidence=0.40, threshold=0.8, deadline_known=True,
            has_conflict=False, has_required_evidence=True,
            aggregator_only=False, aggregator_min_confidence=0.60,
        )
        == "partial"
    )


def test_aggregator_floor_is_off_by_default() -> None:
    """既定値 0.0 のとき、この規則は何も変えない。"""
    assert (
        derive_validation_status(
            confidence=0.10, threshold=0.8, deadline_known=True,
            has_conflict=False, has_required_evidence=True,
            aggregator_only=True,
        )
        == "partial"
    )


def test_score_event_holds_back_an_aggregator_only_candidate() -> None:
    """集約サイト1件だけが根拠で、締切も無い候補は表示しない。"""
    event = make_event(
        event_id="agg", title="集約サイト掲載イベント 2026", start=NOW,
        official="https://matome.example.jp/e",
    )
    evidence = [
        Evidence(
            evidenceId="ev-agg-1",
            sourceUrl="https://matome.example.jp/e",
            sourceType="aggregator",
            supports=["title", "dates.eventStart"],
            retrievedAt=NOW,
        )
    ]

    scored = score_event(
        event, evidence, threshold=0.8, target_year=NOW.year,
        aggregator_min_confidence=0.60,
    )

    assert scored.confidence < 0.60
    assert scored.validation_status == "quarantined"


# ---- §6.7 dedup ----

def test_same_official_url_merges() -> None:
    a = make_event(event_id="a", title="X 2026", start=NOW, official="https://e.com/x")
    b = make_event(
        event_id="b", title="まったく別の名前", start=NOW,
        official="https://WWW.e.com/x/?utm_source=z",
    )
    assert len(group_duplicates([a, b], similarity_threshold=0.80)) == 1


def test_same_application_url_merges() -> None:
    a = make_event(
        event_id="a", title="X 2026", start=NOW, official="https://a.com/x",
        application_url="https://apply.example/1",
    )
    b = make_event(
        event_id="b", title="Y 2026", start=NOW, official="https://b.com/y",
        application_url="https://apply.example/1",
    )
    assert len(group_duplicates([a, b], similarity_threshold=0.80)) == 1


@pytest.mark.parametrize(
    ("left", "right", "same_date", "same_region", "should_merge"),
    [
        # 実測した比率にもとづく境界。閾値0.80。
        ("Gemini API ハッカソン 2026", "Gemini API ハッカソン 2026 in 大阪", True, True, True),
        ("Cloud Builders Kansai", "Cloud Builders Kansai 2026", True, True, True),
        ("大阪データ活用カンファレンス", "大阪データ活用カンファレンス 2026 秋", True, True, True),
        # 類似度は高いが地域が違うので併合しない（0.878）
        ("Cloud Builders Kansai", "Cloud Builders Kanto", True, False, False),
        # 類似度が低い（0.750）
        ("生成AI ハッカソン 2026", "生成AI カンファレンス 2026", True, True, False),
    ],
)
def test_title_similarity_needs_date_and_region(
    left: str, right: str, same_date: bool, same_region: bool, should_merge: bool
) -> None:
    other_start = NOW if same_date else NOW + timedelta(days=30)
    a = make_event(event_id="a", title=left, start=NOW, official="https://a.com/1", region="関西")
    b = make_event(
        event_id="b", title=right, start=other_start, official="https://b.com/2",
        region="関西" if same_region else "関東", organizer="Other",
    )
    groups = group_duplicates([a, b], similarity_threshold=0.80)
    assert (len(groups) == 1) is should_merge


def test_different_year_is_a_different_event() -> None:
    """§6.7「同一イベントの別年度は別イベントとして扱う」。類似度0.952でも分ける。"""
    a = make_event(
        event_id="a", title="Gemini API ハッカソン 2026",
        start=datetime(2026, 10, 11, tzinfo=JST), official="https://e.com/2026",
    )
    b = make_event(
        event_id="b", title="Gemini API ハッカソン 2027",
        start=datetime(2027, 10, 11, tzinfo=JST), official="https://e.com/2027",
    )
    assert title_similarity(normalize_title(a.title), normalize_title(b.title)) > 0.9
    assert len(group_duplicates([a, b], similarity_threshold=0.80)) == 2


def test_merge_keeps_survivor_date_and_flags_disagreement() -> None:
    a = make_event(
        event_id="a", title="X 2026", start=datetime(2026, 10, 18, tzinfo=JST),
        official="https://e.com/x", confidence=0.95,
    )
    a = a.model_copy(update={"validation_status": "verified", "evidence_ids": ["e1"]})
    b = make_event(
        event_id="b", title="X 2026", start=datetime(2026, 10, 19, tzinfo=JST),
        official="https://WWW.e.com/x", confidence=0.60,
    )
    b = b.model_copy(update={"evidence_ids": ["e2"]})
    merged = merge_group([a, b])
    assert merged.dates.event_start.date() == a.dates.event_start.date()
    assert set(merged.evidence_ids) == {"e1", "e2"}
    # 日付が食い違うので verified のままにしない
    assert merged.validation_status == "partial"


def test_normalize_url_drops_tracking_and_case() -> None:
    assert normalize_url("HTTPS://WWW.Example.com/a/?utm_source=x&id=3") == (
        "https://example.com/a?id=3"
    )


# ---- §6.8 scoring ----

def _evidence(source_type: str, url: str, supports: list[str]) -> Evidence:
    return Evidence(
        evidenceId=f"e-{url}",
        sourceUrl=url,
        sourceType=source_type,
        supports=supports,
        retrievedAt=NOW,
    )


def test_score_is_bounded_and_deterministic() -> None:
    prefs = UserPreferences(
        interestsPrompt="ハッカソン 生成AI", targetYear=2026,
        onlineAllowed=True, locations=["大阪"],
    )
    event = make_event(
        event_id="a", title="生成AI ハッカソン", start=datetime(2026, 11, 1, tzinfo=JST),
        official="https://e.com/x", deadline=datetime(2026, 10, 20, tzinfo=JST),
    )
    evidence = [
        _evidence("official", "https://e.com/x", ["title", "dates.eventStart"]),
        _evidence("aggregator", "https://agg.com/x", ["dates.applicationDeadline"]),
    ]
    first = score_recommendation(event, evidence, prefs, now=NOW)
    second = score_recommendation(event, evidence, prefs, now=NOW)
    assert first == second
    assert 0 <= first <= 100


def test_score_rewards_region_and_official_source() -> None:
    prefs = UserPreferences(
        interestsPrompt="ハッカソン", targetYear=2026, onlineAllowed=True, locations=["大阪"]
    )
    start = datetime(2026, 11, 1, tzinfo=JST)
    deadline = datetime(2026, 10, 20, tzinfo=JST)
    local = make_event(
        event_id="a", title="ハッカソン", start=start, official="https://e.com/x",
        region="大阪", deadline=deadline,
    )
    far = make_event(
        event_id="b", title="ハッカソン", start=start, official="https://e.com/y",
        region="北海道", deadline=deadline,
    )
    official = [_evidence("official", "https://e.com/x", ["title", "dates.eventStart"])]
    aggregator = [_evidence("aggregator", "https://agg.com/y", ["title"])]
    assert score_recommendation(local, official, prefs, now=NOW) > score_recommendation(
        far, aggregator, prefs, now=NOW
    )


def test_unknown_deadline_scores_between_urgent_and_distant() -> None:
    prefs = UserPreferences(
        interestsPrompt="ハッカソン", targetYear=2026, onlineAllowed=True, locations=["大阪"]
    )
    start = datetime(2026, 11, 1, tzinfo=JST)
    base = dict(title="ハッカソン", start=start, official="https://e.com/x")
    ev = [_evidence("official", "https://e.com/x", ["title", "dates.eventStart"])]
    unknown = score_recommendation(make_event(event_id="u", deadline=None, **base), ev, prefs, now=NOW)
    distant = score_recommendation(
        make_event(event_id="d", deadline=datetime(2026, 10, 20, tzinfo=JST), **base), ev, prefs, now=NOW
    )
    assert unknown < distant


def test_conflicting_sources_merge_within_the_date_window() -> None:
    """日付が食い違う2ソースは、タイトル・地域・主催者が揃えば併合する。

    §6.7「開催日変更は履歴を残し、無条件で上書きしない」は、日付の異なる重複が
    起こりうることを前提にしている。
    """
    a = make_event(
        event_id="a", title="矛盾テスト 2026", start=datetime(2026, 10, 18, tzinfo=JST),
        official="https://official.example.jp/e", region="大阪",
    )
    b = make_event(
        event_id="b", title="矛盾テスト 2026", start=datetime(2026, 10, 19, tzinfo=JST),
        official="https://agg.example.com/e", region="大阪",
    )
    assert len(group_duplicates([a, b], similarity_threshold=0.80)) == 1


def test_date_window_does_not_merge_distant_editions() -> None:
    """窓の外（春と秋、別年度）は併合しない。"""
    spring = make_event(
        event_id="a", title="AI Meetup 2026", start=datetime(2026, 4, 1, tzinfo=JST),
        official="https://e.example.jp/spring", region="大阪",
    )
    autumn = make_event(
        event_id="b", title="AI Meetup 2026", start=datetime(2026, 10, 1, tzinfo=JST),
        official="https://e.example.jp/autumn", region="大阪",
    )
    assert len(group_duplicates([spring, autumn], similarity_threshold=0.80)) == 2


def test_date_window_requires_compatible_organizer() -> None:
    a = make_event(
        event_id="a", title="別主催テスト 2026", start=datetime(2026, 10, 18, tzinfo=JST),
        official="https://a.example.jp/e", region="大阪", organizer="A社",
    )
    b = make_event(
        event_id="b", title="別主催テスト 2026", start=datetime(2026, 10, 19, tzinfo=JST),
        official="https://b.example.jp/e", region="大阪", organizer="B社",
    )
    assert len(group_duplicates([a, b], similarity_threshold=0.80)) == 2
