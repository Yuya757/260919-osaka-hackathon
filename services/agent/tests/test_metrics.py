"""主催者確認・PR 枠・成果計測（ADR-009）。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import FROZEN_NOW
from event_agent.domain.outbound import with_utm
from event_agent.entrypoints.admin import main as admin_main
from event_agent.entrypoints.service import app
from event_agent.schemas import OrganizerPostRequest, UserPreferences
from event_agent.storage.store import effective_placement
from event_agent.workflows.collect import run_collect_workflow
from event_agent.workflows.organizer_posts import confirm_post, create_post, pin_post, seed_bot_posts

BODY = "開催日: 2026年10月16日 10:00\n申込締切: 2026年9月30日 23:59\n会場: グランフロント大阪"


def make_post(**overrides):
    fields = {
        "organizerName": "関西イノベーションセンター",
        "contactUrl": "https://kansai-innovation.example.jp/hackathon2026?ref=x",
        "title": "関西 Generative AI Hackathon 2026",
        "body": BODY,
    }
    fields.update(overrides)
    post, _ = create_post(OrganizerPostRequest(**fields), now=FROZEN_NOW)
    return post


def test_with_utm_merges_existing_query():
    url = with_utm("https://example.com/e?ref=x&utm_source=old#top", "evt-1")
    assert url == "https://example.com/e?ref=x&utm_source=cho-event-kanri&utm_medium=app&utm_campaign=evt-1#top"


def test_confirm_survives_resubmission_and_refuses_bots(store_backend):
    post = make_post()
    assert post.organizer_confirmed is False
    confirmed = confirm_post(post.post_id, now=FROZEN_NOW)
    assert confirmed.organizer_confirmed and confirmed.confirmed_at == FROZEN_NOW
    again = make_post(body=BODY + "\n追記あり")
    assert again.post_id == post.post_id and again.organizer_confirmed

    from event_agent.demo.catalog import demo_catalog

    bot = seed_bot_posts(demo_catalog()[:1], now=FROZEN_NOW)[0]
    with pytest.raises(ValueError):
        confirm_post(bot.post_id, now=FROZEN_NOW)


def test_pin_expires(store_backend):
    post = make_post()
    pinned = pin_post(post.post_id, until=FROZEN_NOW + timedelta(days=7), now=FROZEN_NOW)
    assert pinned.placement.kind == "pinned"
    assert effective_placement(pinned, FROZEN_NOW).kind == "pinned"
    assert effective_placement(pinned, FROZEN_NOW + timedelta(days=8)).kind == "normal"


@pytest.mark.asyncio
async def test_outbound_redirect_counts_and_adds_utm(store_backend):
    await run_collect_workflow(UserPreferences(), True, now=FROZEN_NOW)
    event = store_backend.list_events()[0]
    assert event.application_url is None  # デモ経路には申込URLが無い → application は 404
    with TestClient(app) as client:
        response = client.get(f"/api/go/{event.event_id}/official", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["cache-control"] == "no-store"
        location = response.headers["location"]
        assert location.startswith(event.official_url.split("?")[0])
        assert f"utm_campaign={event.event_id}" in location and "utm_source=cho-event-kanri" in location
        client.get(f"/api/go/{event.event_id}/official", follow_redirects=False)
        assert client.get(f"/api/go/{event.event_id}/application", follow_redirects=False).status_code == 404
        assert client.post(f"/api/events/{event.event_id}/metrics", json={"kind": "calendar"}).status_code == 204
        assert client.post(f"/api/events/{event.event_id}/metrics", json={"kind": "x"}).status_code == 422
        assert client.get("/api/go/missing/official", follow_redirects=False).status_code == 404
        assert client.get(f"/api/go/{event.event_id}/nope", follow_redirects=False).status_code == 404

    metrics = store_backend.get_event_metrics(event.event_id)
    assert metrics.clicks.official == 2 and metrics.clicks.application == 0 and metrics.calendar == 1
    day = next(iter(metrics.daily.values()))
    assert day.clicks == 2 and day.calendar == 1
    assert store_backend.get_event_metrics("missing") is None


@pytest.mark.asyncio
async def test_post_metrics_include_linked_event(store_backend):
    await run_collect_workflow(UserPreferences(), True, now=FROZEN_NOW)
    collected = next(e for e in store_backend.list_events() if "Gemini API" in e.title)
    post = make_post(
        title=collected.title,
        organizerName=collected.organizer or "Google for Developers",
        body="開催日: 2026年10月11日 10:00\n申込締切: 2026年9月22日 23:59",
    )
    assert post.linked_event_id == collected.event_id
    with TestClient(app) as client:
        client.get(f"/api/go/{collected.event_id}/official", follow_redirects=False)
        client.get(f"/api/go/{post.event.event_id}/contact", follow_redirects=False)
        body = client.get(f"/api/organizer-posts/{post.post_id}/metrics").json()
    assert body["eventId"] == post.event.event_id and body["linkedEventId"] == collected.event_id
    assert body["metrics"]["clicks"]["contact"] == 1
    assert body["linkedMetrics"]["clicks"]["official"] == 1


def test_admin_cli(store_backend, capsys):
    post = make_post()
    assert admin_main(["confirm", post.post_id]) == 0
    assert '"organizerConfirmed": true' in capsys.readouterr().out
    assert admin_main(["pin", post.post_id, "--until", "2026-10-15"]) == 0
    assert admin_main(["metrics", post.post_id]) == 0
    assert admin_main(["confirm", "missing"]) == 2
    assert admin_main(["hide", post.post_id]) == 0
    assert store_backend.get_organizer_post(post.post_id).status == "hidden"


def test_calendar_counts_list_only_registered_events(store_backend):
    store = store_backend
    store.increment_event_metric("evt-a", "calendar", jst_date="2026-09-25")
    store.increment_event_metric("evt-a", "calendar", jst_date="2026-09-26")
    store.increment_event_metric("evt-b", "official", jst_date="2026-09-25")
    assert store.list_calendar_counts() == {"evt-a": 2}
    response = TestClient(app).get("/api/calendar-counts")
    assert response.status_code == 200 and response.json() == {"counts": {"evt-a": 2}}
