"""主催者の申請・本人確認・編集（ADR-013）。

確かめること: 確認コードがページに無ければ鍵を渡さない、鍵は一度だけ渡しハッシュしか
持たない、鍵が違えば編集できない、主催者の値は再収集でも消えない、締切だけ欠けて
partial だったイベントは主催者の締切で verified になる、おかしな値は弾く。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import FROZEN_NOW
from event_agent.clients.page_fetcher import FixturePage, FixturePageSource, page_fetcher
from event_agent.entrypoints.service import app
from event_agent.schemas import OrganizerEditValues
from event_agent.workflows import event_claims
from event_agent.workflows.collect import run_theme_collection
from event_agent.workflows.event_claims import ClaimError, edit_event, start_claim, verify_claim
from event_agent.workflows.themes import theme_by_id

NOW = FROZEN_NOW


async def _collected_meetup(store):
    await run_theme_collection(theme_by_id("meetup-study"), now=NOW)
    event = next(e for e in store.list_events() if e.title.startswith("Python もくもく会"))
    assert event.validation_status == "partial" and event.dates.application_deadline is None
    return event


def _pages(monkeypatch, url: str, body: str):
    monkeypatch.setattr(
        page_fetcher, "_source", FixturePageSource({url: FixturePage(body=body)})
    )


@pytest.mark.asyncio
async def test_code_on_the_page_hands_out_a_token_once(store_backend, monkeypatch):
    event = await _collected_meetup(store_backend)
    claim = start_claim(event.event_id, now=NOW)
    assert claim.code.startswith("CHO-") and claim.page_urls == [event.official_url]

    _pages(monkeypatch, event.official_url, "<html><body>イベント説明</body></html>")
    missing = await verify_claim(claim.claim_id, now=NOW)
    assert missing.status == "code_not_found" and missing.edit_token is None

    _pages(monkeypatch, event.official_url, f"<html><body>確認用: {claim.code.lower()}</body></html>")
    verified = await verify_claim(claim.claim_id, now=NOW)
    assert verified.status == "verified" and verified.edit_token
    stored = store_backend.get_claim(claim.claim_id)
    assert stored.edit_token_hash and verified.edit_token not in stored.model_dump_json()

    with pytest.raises(ClaimError) as again:
        await verify_claim(claim.claim_id, now=NOW)
    assert again.value.status == 409


@pytest.mark.asyncio
async def test_unreadable_page_expiry_and_attempt_limit(store_backend, monkeypatch):
    event = await _collected_meetup(store_backend)
    claim = start_claim(event.event_id, now=NOW)
    _pages(monkeypatch, "https://other.example/", "x")
    assert (await verify_claim(claim.claim_id, now=NOW)).status == "page_unavailable"

    late = NOW + event_claims.CLAIM_TTL + timedelta(minutes=1)
    assert (await verify_claim(claim.claim_id, now=late)).status == "expired"

    for _ in range(event_claims.MAX_ATTEMPTS):
        await verify_claim(claim.claim_id, now=NOW)
    assert (await verify_claim(claim.claim_id, now=NOW)).status == "too_many_attempts"


async def _verified(store, monkeypatch):
    event = await _collected_meetup(store)
    claim = start_claim(event.event_id, now=NOW)
    _pages(monkeypatch, event.official_url, f"<p>{claim.code}</p>")
    result = await verify_claim(claim.claim_id, now=NOW)
    return event, claim.claim_id, result.edit_token


@pytest.mark.asyncio
async def test_organizer_edit_fills_station_and_deadline_and_survives_recollection(
    store_backend, monkeypatch
):
    event, claim_id, token = await _verified(store_backend, monkeypatch)
    deadline = event.dates.event_start - timedelta(days=1)
    edited = edit_event(
        claim_id,
        token,
        OrganizerEditValues(nearestStation="梅田駅", applicationDeadline=deadline),
        now=NOW,
    )
    assert edited.location.nearest_station == "梅田"
    assert edited.dates.application_deadline == deadline
    # 締切だけ欠けて partial だったので、主催者の締切で verified になる
    assert edited.validation_status == "verified"
    assert edited.organizer_edit and edited.organizer_edit.page_url == event.official_url

    # 毎朝の再収集で上書きされても、主催者の値は残る
    _, started = await run_theme_collection(theme_by_id("meetup-study"), now=NOW + timedelta(days=1))
    assert started
    again = store_backend.get_event(event.event_id)
    assert again.location.nearest_station == "梅田"
    assert again.dates.application_deadline == deadline

    # 次の編集は前の値に足す
    later = edit_event(claim_id, token, OrganizerEditValues(venue="新しい会場"), now=NOW)
    assert later.location.venue == "新しい会場" and later.location.nearest_station == "梅田"


@pytest.mark.asyncio
async def test_wrong_token_and_bad_values_are_refused(store_backend, monkeypatch):
    event, claim_id, token = await _verified(store_backend, monkeypatch)
    with pytest.raises(ClaimError) as wrong:
        edit_event(claim_id, "not-the-token", OrganizerEditValues(venue="x"), now=NOW)
    assert wrong.value.status == 403

    after_start = event.dates.event_start + timedelta(hours=1)
    for values in (
        OrganizerEditValues(applicationDeadline=after_start),
        OrganizerEditValues(applicationDeadline=NOW - timedelta(days=1)),
        OrganizerEditValues(applicationUrl="http://insecure.example/apply"),
        OrganizerEditValues(applicationUrl="https://127.0.0.1/apply"),
    ):
        with pytest.raises(ClaimError) as bad:
            edit_event(claim_id, token, values, now=NOW)
        assert bad.value.status == 422

    expired = NOW + event_claims.TOKEN_TTL + timedelta(seconds=1)
    with pytest.raises(ClaimError) as late:
        edit_event(claim_id, token, OrganizerEditValues(venue="x"), now=expired)
    assert late.value.status == 403


def test_endpoints_refuse_unknown_events_and_claims(store_backend):
    with TestClient(app) as client:
        assert client.post("/api/event-claims", json={"eventId": "nope"}).status_code == 404
        assert client.post("/api/event-claims/verify", json={"claimId": "nope"}).status_code == 404
        response = client.post(
            "/api/event-claims/edit",
            json={"claimId": "nope", "editToken": "x", "values": {"venue": "v"}},
        )
        assert response.status_code == 403
