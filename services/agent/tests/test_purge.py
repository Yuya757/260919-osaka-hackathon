"""検索グラウンディング由来のデータを消す（ADR-014）。

確かめること: dry-run は何も消さずに件数だけを出す。apply は検索テーマで集めた
イベント・Run・根拠・ボット投稿・申請を消し、Doorkeeper 由来と利用者が登録したページ、
主催者投稿は残す（主催者投稿の結び付きだけ外す）。
"""

from __future__ import annotations

import json

import pytest

from conftest import FROZEN_NOW
from event_agent.clients import robots
from event_agent.clients.page_fetcher import FixturePage, FixturePageSource, page_fetcher
from event_agent.entrypoints import admin
from event_agent.schemas import EventClaim
from event_agent.workflows.collect import run_theme_collection
from event_agent.workflows.purge import apply_purge, is_grounding_derived, plan_purge
from event_agent.workflows.themes import theme_by_id
from event_agent.workflows.watched_pages import register_page

URL = "https://hack.example.jp/registered"
PAGE = """<html><head><title>神戸 IoT ハッカソン 2026</title></head><body>
<h1>神戸 IoT ハッカソン 2026</h1>
<div>開催日時: 2026年10月24日 10:00〜10月25日 18:00</div>
<div>申込締切: 2026年10月17日 23:59</div>
<div>会場: 神戸市産業振興センター</div>
</body></html>"""


async def _seed(store, monkeypatch):
    await run_theme_collection(theme_by_id("hackathon-kansai"), now=FROZEN_NOW)
    await run_theme_collection(theme_by_id("meetup-study"), now=FROZEN_NOW)
    robots.clear_cache()
    monkeypatch.setattr(
        page_fetcher, "_source", FixturePageSource({URL: FixturePage(body=PAGE)})
    )
    registered = await register_page(URL, "s1", now=FROZEN_NOW)
    assert registered.status == "added", registered.message
    events = store.list_all_events()
    grounded = [e for e in events if e.theme_id == "hackathon-kansai"]
    assert grounded, "デモの検索テーマがイベントを作っていない"
    target = grounded[0]
    store.save_claim(
        EventClaim(
            claimId="claim-1",
            eventId=target.event_id,
            code="CHO-AAAA-BBBB",
            pageUrls=[target.official_url],
            createdAt=FROZEN_NOW,
            expiresAt=FROZEN_NOW,
        )
    )
    organizer = next(p for p in store.list_organizer_posts() if p.origin == "bot")
    store.save_organizer_post(
        organizer.model_copy(
            update={"post_id": "organizer-1", "origin": "organizer", "linked_event_id": target.event_id}
        )
    )
    return target


@pytest.mark.asyncio
async def test_dry_run_counts_without_deleting(store_backend, monkeypatch, capsys):
    await _seed(store_backend, monkeypatch)
    before = len(store_backend.list_all_events())

    assert admin.main(["purge-grounding", "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["applied"] is False
    assert report["events"] > 0 and report["claims"] == 1
    assert report["organizerPostsToUnlink"] == 1
    assert set(report["eventsByTheme"]) == {"hackathon-kansai"}
    assert len(store_backend.list_all_events()) == before


@pytest.mark.asyncio
async def test_apply_removes_grounding_data_and_keeps_the_rest(store_backend, monkeypatch):
    target = await _seed(store_backend, monkeypatch)
    plan = plan_purge()
    run_id = target.source_run_id

    apply_purge(plan)

    left = store_backend.list_all_events()
    assert left and not any(is_grounding_derived(e) for e in left)
    assert {e.theme_id for e in left} == {"meetup-study", "user-registered"}
    assert store_backend.get_run(run_id) is None
    assert store_backend.get_evidence(run_id, target.evidence_ids) == []
    assert store_backend.get_claim("claim-1") is None

    posts = store_backend.list_organizer_posts()
    bot_keys = {p.linked_dedup_key for p in posts if p.origin == "bot"}
    assert bot_keys <= {e.dedup_key for e in left}
    organizer = store_backend.get_organizer_post("organizer-1")
    assert organizer is not None and organizer.linked_event_id is None

    # 2 回目は何も残っていない
    assert plan_purge().summary()["events"] == 0
