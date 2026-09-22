"""主催者投稿フィード（F-06 / ADR-006）。

投稿本文からの抽出はページ抽出と同じ規則で動くこと、投稿が AI 収集イベントを
書き換えないこと、ボット投稿が冪等であることを、両方のストアで確かめる。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from event_agent.entrypoints.service import app
from event_agent.extraction.post_text import derive_event_from_post
from event_agent.schemas import OrganizerPostRequest, PostPlacement, UserPreferences
from event_agent.security.prompt_guard import clean_multiline
from event_agent.workflows.collect import run_collect_workflow
from event_agent.workflows.organizer_posts import (
    PostRejected,
    create_post,
    list_feed,
    preview_post,
    seed_bot_posts,
)
from conftest import FROZEN_NOW
from test_chat_defense import ATTACK

CONTACT = "https://kansai-innovation.example.jp/hackathon2026"


def request(body: str, **overrides) -> OrganizerPostRequest:
    fields = {
        "organizerName": "関西イノベーションセンター",
        "contactUrl": CONTACT,
        "title": "関西 Generative AI Hackathon 2026",
        "body": body,
    }
    fields.update(overrides)
    return OrganizerPostRequest(**fields)


FULL_BODY = (
    "生成AIをテーマにした2泊3日のハッカソン。\n"
    "開催日: 2026年10月16日 10:00 〜 2026年10月18日 18:00\n"
    "申込締切: 2026年9月30日 23:59\n"
    "会場: グランフロント大阪\n"
)


# ------------------------------------------------------------- extraction


class TestDeriveEvent:
    def test_full_dates_are_verified(self):
        draft = derive_event_from_post(request(FULL_BODY), now=FROZEN_NOW)
        assert draft.ok()
        event = draft.event
        assert event is not None
        assert event.validation_status == "verified"
        assert event.dates.application_deadline_precision == "datetime"
        assert event.dates.event_start.day == 16 and event.dates.event_end.day == 18
        assert event.location.venue == "グランフロント大阪"
        assert event.category == "hackathon"
        assert event.event_id.startswith("post-")
        assert event.source_run_id == "organizer-posts"
        assert {e.source_type for e in draft.evidence} == {"organizer"}
        assert all(e.source_url == CONTACT for e in draft.evidence)
        supported = {field for e in draft.evidence for field in e.supports}
        assert {"title", "dates.eventStart", "dates.applicationDeadline"} <= supported

    def test_missing_deadline_is_partial_with_warning(self):
        draft = derive_event_from_post(
            request("開催日: 2026年10月16日 10:00\n会場: 大阪"), now=FROZEN_NOW
        )
        assert draft.ok()
        assert draft.event.validation_status == "partial"
        assert draft.event.dates.application_deadline is None
        assert draft.event.dates.application_deadline_precision == "unknown"
        assert [i.code for i in draft.warnings] == ["DEADLINE_MISSING"]

    def test_missing_event_date_is_an_error(self):
        draft = derive_event_from_post(request("楽しいイベントです。ぜひ来てください。"), now=FROZEN_NOW)
        assert draft.event is None
        assert [i.code for i in draft.errors] == ["EVENT_DATE_MISSING"]

    def test_year_is_never_inferred(self):
        # 年が2つ出てくる本文では、年なしの開催日を補完しない（§6.5）
        body = "2025年の第1回に続く第2回です。2027年も予定。\n開催日: 10月16日 10:00"
        draft = derive_event_from_post(request(body), now=FROZEN_NOW)
        assert draft.event is None
        assert [i.code for i in draft.errors] == ["YEAR_AMBIGUOUS"]

    def test_single_year_in_body_completes_the_date(self):
        body = "2026年開催。\n開催日: 10月16日 10:00\n申込締切: 9月30日"
        draft = derive_event_from_post(request(body), now=FROZEN_NOW)
        assert draft.ok()
        assert draft.event.dates.event_start.year == 2026
        assert draft.event.dates.application_deadline_precision == "date"
        # 日付のみの締切でも閾値 0.8 を越える（丸め後 0.81）。時刻は捏造しない
        assert draft.event.validation_status == "verified"
        assert draft.event.confidence >= 0.8

    def test_finished_event_is_rejected(self):
        draft = derive_event_from_post(
            request("開催日: 2026年9月1日 10:00\n申込締切: 2026年8月20日 23:59"), now=FROZEN_NOW
        )
        assert [i.code for i in draft.errors] == ["EVENT_FINISHED"]

    def test_deadline_after_event_is_a_conflict(self):
        draft = derive_event_from_post(
            request("開催日: 2026年10月16日 10:00\n申込締切: 2026年10月20日 23:59"), now=FROZEN_NOW
        )
        assert [i.code for i in draft.errors] == ["DATE_CONFLICT"]

    def test_early_bird_deadline_is_not_the_application_deadline(self):
        body = "開催日: 2026年10月16日 10:00\n早期申込締切: 2026年9月10日\n"
        draft = derive_event_from_post(request(body), now=FROZEN_NOW)
        assert draft.event.dates.application_deadline is None
        assert [i.code for i in draft.warnings] == ["DEADLINE_MISSING"]

    def test_clean_multiline_keeps_line_structure(self):
        cleaned = clean_multiline("開催日: 2026年10月16日\r\n\r\n\r\n\r\n申込締切: 2026年9月30日\x00", max_chars=4000)
        assert cleaned == "開催日: 2026年10月16日\n\n申込締切: 2026年9月30日"


# -------------------------------------------------------------------- API


@pytest.fixture
def client(store_backend):
    with TestClient(app) as test_client:
        yield test_client


def payload(body: str = FULL_BODY, **overrides) -> dict:
    return request(body, **overrides).model_dump(by_alias=True)


class TestApi:
    def test_preview_writes_nothing(self, client: TestClient, store_backend):
        response = client.post("/api/organizer-posts/preview", json=payload("開催日: 2026年10月16日 10:00"))
        assert response.status_code == 200
        body = response.json()
        assert body["event"]["validationStatus"] == "partial"
        assert [i["code"] for i in body["issues"]] == ["DEADLINE_MISSING"]
        assert store_backend.list_organizer_posts() == []

    def test_create_then_feed(self, client: TestClient):
        created = client.post("/api/organizer-posts", json=payload())
        assert created.status_code == 201, created.text
        post = created.json()["post"]
        assert post["origin"] == "organizer"
        assert post["placement"] == {"kind": "normal", "until": None}
        assert post["event"]["eventId"] == post["postId"]

        feed = client.get("/api/organizer-posts").json()["posts"]
        assert [p["postId"] for p in feed] == [post["postId"]]

    def test_create_is_idempotent(self, client: TestClient):
        first = client.post("/api/organizer-posts", json=payload()).json()["post"]
        second = client.post("/api/organizer-posts", json=payload()).json()["post"]
        assert first["postId"] == second["postId"]
        assert first["createdAt"] == second["createdAt"]
        assert len(client.get("/api/organizer-posts").json()["posts"]) == 1

    def test_injection_is_rejected_and_not_stored(self, client: TestClient, store_backend):
        response = client.post("/api/organizer-posts", json=payload(FULL_BODY + ATTACK))
        assert response.status_code == 400
        assert response.json()["detail"] == "投稿内容を受け付けられませんでした。"
        assert ATTACK not in response.text
        assert store_backend.list_organizer_posts() == []

    def test_private_contact_url_is_rejected(self, client: TestClient):
        for url in ("http://localhost:3000/event", "http://10.0.0.1/event", "ftp://example.com/x"):
            response = client.post("/api/organizer-posts", json=payload(contactUrl=url))
            assert response.status_code == 400, url

    def test_private_url_in_body_is_flagged_not_blocked(self, client: TestClient):
        response = client.post(
            "/api/organizer-posts", json=payload(FULL_BODY + "\n参考: http://10.0.0.1/internal")
        )
        assert response.status_code == 201
        assert response.json()["post"]["injectionFlags"] == ["PRIVATE_URL_REFERENCE"]

    def test_missing_event_date_is_a_400_with_the_hint(self, client: TestClient):
        response = client.post("/api/organizer-posts", json=payload("日程は追って告知します。"))
        assert response.status_code == 400
        assert "開催日" in response.json()["detail"]

    def test_body_over_limit_is_422(self, client: TestClient):
        response = client.post("/api/organizer-posts", json={**payload(), "body": "あ" * 4001})
        assert response.status_code == 422


# ------------------------------------------------------- dedup & bot seeding


@pytest.mark.asyncio
async def test_post_links_to_collected_event_without_rewriting_it(store_backend):
    await run_collect_workflow(UserPreferences(), True, now=FROZEN_NOW)
    collected = next(e for e in store_backend.list_events() if "Gemini API" in e.title)
    before = collected.model_dump()

    post, warnings = create_post(
        request(
            "開催日: 2026年10月11日 10:00 〜 2026年10月12日 18:00\n申込締切: 2026年9月22日 23:59\n会場: グランフロント大阪",
            title=collected.title,
            organizerName=collected.organizer or "Google for Developers",
            contactUrl="https://example.org/mirror",
        ),
        now=FROZEN_NOW,
    )
    assert post.linked_event_id == collected.event_id
    assert post.linked_dedup_key == collected.dedup_key
    assert [w.code for w in warnings] == ["DUPLICATE_OF_EVENT"]
    # AI 側は不変
    assert store_backend.get_event(collected.event_id).model_dump() == before

    feed = list_feed(now=FROZEN_NOW)
    assert post.post_id in {p.post_id for p in feed}
    # 同じイベントのボット投稿は主催者投稿に譲る
    assert not any(p.origin == "bot" and p.linked_dedup_key == collected.dedup_key for p in feed)


@pytest.mark.asyncio
async def test_preview_reports_duplicate(store_backend):
    await run_collect_workflow(UserPreferences(), True, now=FROZEN_NOW)
    collected = next(e for e in store_backend.list_events() if "Gemini API" in e.title)
    draft, linked = preview_post(
        request(
            "開催日: 2026年10月11日 10:00\n申込締切: 2026年9月22日 23:59",
            title=collected.title,
            organizerName=collected.organizer or "Google for Developers",
        ),
        now=FROZEN_NOW,
    )
    assert linked is not None and linked.event_id == collected.event_id
    assert "DUPLICATE_OF_EVENT" in [i.code for i in draft.issues]
    # プレビューは書かない。あるのは Run が流したボット投稿だけ
    assert all(p.origin == "bot" for p in store_backend.list_organizer_posts())


@pytest.mark.asyncio
async def test_bot_seeding_is_idempotent(store_backend):
    await run_collect_workflow(UserPreferences(), True, now=FROZEN_NOW)
    first = {p.post_id: p for p in store_backend.list_organizer_posts()}
    assert first and all(pid.startswith("bot-") for pid in first)
    assert all(p.origin == "bot" and p.linked_event_id for p in first.values())

    await run_collect_workflow(UserPreferences(), True, now=FROZEN_NOW + timedelta(days=1))
    second = {p.post_id: p for p in store_backend.list_organizer_posts()}
    assert second.keys() == first.keys()
    assert all(second[pid].created_at == first[pid].created_at for pid in first)


def test_feed_order_and_visibility(store_backend):
    from event_agent.demo.catalog import demo_catalog

    seeded = seed_bot_posts(demo_catalog(), now=FROZEN_NOW)
    assert len(seeded) >= 4
    pinned, hidden, expired, prioritized, *_ = seeded

    store_backend.update_post_state(pinned.post_id, placement=PostPlacement(kind="pinned"))
    store_backend.update_post_state(hidden.post_id, status="hidden")
    store_backend.update_post_state(
        expired.post_id,
        placement=PostPlacement(kind="priority", until=FROZEN_NOW - timedelta(days=1)),
    )
    store_backend.update_post_state(
        prioritized.post_id,
        placement=PostPlacement(kind="priority", until=FROZEN_NOW + timedelta(days=7)),
    )
    # 再投稿しても固定・優先・非表示は保持される（投稿者がリセットできない）
    seed_bot_posts(demo_catalog(), now=FROZEN_NOW + timedelta(hours=1))

    feed = list_feed(now=FROZEN_NOW)
    ids = [p.post_id for p in feed]
    assert ids[:2] == [pinned.post_id, prioritized.post_id]
    assert hidden.post_id not in ids
    # 期限切れの優先枠は通常扱い
    assert ids.index(expired.post_id) >= 2


def test_posts_without_an_event_date_stay_in_the_feed(store_backend):
    """実施日の無い告知（ビジコン）は締切で終わりを判定する。

    以前は `eventEnd or eventStart` を now と比べていたので、実施日が無い
    イベントのボット投稿があるだけでフィード全体が落ちた。
    """
    from event_agent.demo.catalog import demo_catalog

    contest = next(e for e in demo_catalog() if e.kind == "contest")
    assert contest.dates.event_start is None
    seed_bot_posts([contest], now=FROZEN_NOW)

    assert [p.event.title for p in list_feed(now=FROZEN_NOW)] == [contest.title]
    # 締切を過ぎたら消える
    after = contest.dates.application_deadline + timedelta(days=1)
    assert list_feed(now=after) == []


def test_rejected_message_is_generic():
    with pytest.raises(PostRejected) as caught:
        create_post(request(FULL_BODY, organizerName=ATTACK), now=FROZEN_NOW)
    assert caught.value.message == "投稿内容を受け付けられませんでした。"
