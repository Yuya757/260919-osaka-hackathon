"""技術イベントを Doorkeeper の公開 API から作る（ADR-012）。

Web 収集と違い抽出が無いので、確かめるのは写し替えと収集の作法:
UTC の開催日時を JST にする、申込締切を作らない、開催形式と地域を住所から決める、
終わったものを載せない、ページ送りを抑える。ネットワークには出ない（デモデータを使う）。
"""

from __future__ import annotations

import pytest

from conftest import FROZEN_NOW
from event_agent.clients.doorkeeper import listing_from_json
from event_agent.demo.meetups import DEMO_ROWS, DemoMeetupSource
from event_agent.workflows.collect import run_theme_collection
from event_agent.workflows.meetups import collect_meetups, event_from_meetup
from event_agent.workflows.pool import candidates as pool_candidates
from event_agent.workflows.themes import theme_by_id


def _row(**event):
    base = {
        "id": 1,
        "title": "Python 勉強会",
        "starts_at": "2026-10-07T10:00:00.000Z",
        "public_url": "https://example.doorkeeper.jp/events/1",
    }
    return {"event": {**base, **event}}


def test_utc_start_becomes_jst_and_no_deadline_is_invented():
    listing = listing_from_json(_row(ends_at="2026-10-07T12:00:00.000Z"))
    assert listing is not None
    assert listing.starts_at.isoformat() == "2026-10-07T19:00:00+09:00"

    event, evidence = event_from_meetup(listing, now=FROZEN_NOW, run_id="r")
    assert event.kind == "meetup" and event.category == "meetup"
    assert event.dates.event_start.isoformat() == "2026-10-07T19:00:00+09:00"
    assert event.dates.event_end.isoformat() == "2026-10-07T21:00:00+09:00"
    # API に締切は無い。推測して埋めない（§6.5）
    assert event.dates.application_deadline is None
    supported = {field for item in evidence for field in item.supports}
    assert {"title", "dates.eventStart"} <= supported
    assert all(item.source_url == "https://example.doorkeeper.jp/events/1" for item in evidence)


def test_organizer_is_the_expanded_group_name():
    named = listing_from_json(_row(group={"id": 5, "name": "梅田Python"}))
    event, _ = event_from_meetup(named, now=FROZEN_NOW, run_id="r")
    assert event.organizer == "梅田Python"
    # expand しなかった応答は id だけ。名前を作らない
    bare = listing_from_json(_row(group=5))
    event, _ = event_from_meetup(bare, now=FROZEN_NOW, run_id="r")
    assert event.organizer is None


def test_rows_without_id_title_https_url_or_start_are_dropped():
    assert listing_from_json({"event": {"title": "t", "public_url": "https://x"}}) is None
    assert listing_from_json(_row(public_url="http://insecure.example/events/1")) is None
    no_start = listing_from_json(_row(starts_at="未定"))
    assert no_start is not None and no_start.starts_at is None
    assert event_from_meetup(no_start, now=FROZEN_NOW, run_id="r") is None


@pytest.mark.parametrize(
    ("venue", "address", "expected", "region"),
    [
        ("グランフロント大阪", "大阪府大阪市北区大深町3-1", "offline", "大阪府"),
        ("オンライン（Zoom）", "", "online", None),
        ("渋谷ストリームホール（オンライン配信あり）", "東京都渋谷区渋谷3-21-3", "hybrid", "東京都"),
        (None, None, "unknown", None),
    ],
)
def test_location_type_and_region_come_from_venue_and_address(venue, address, expected, region):
    listing = listing_from_json(_row(venue_name=venue, address=address))
    event, _ = event_from_meetup(listing, now=FROZEN_NOW, run_id="r")
    assert event.location.type == expected
    assert event.location.region == region


def test_description_html_is_stripped_and_capped():
    listing = listing_from_json(_row(description="<p>初心者<b>歓迎</b></p>" + "あ" * 400))
    event, _ = event_from_meetup(listing, now=FROZEN_NOW, run_id="r")
    assert "<" not in event.summary
    assert event.summary.startswith("初心者")
    assert len(event.summary) <= 200


@pytest.mark.asyncio
async def test_collect_dedupes_across_keywords_and_stops_paging_on_a_short_page():
    source = DemoMeetupSource()
    theme = theme_by_id("meetup-study")
    candidates, calls = await collect_meetups(theme, run_id="r", now=FROZEN_NOW, source=source)

    ids = [c.event.event_id for c in candidates]
    assert len(ids) == len(set(ids))
    # 1 ページ目が 25 件未満なら 2 ページ目を引かない
    assert all(page == 1 for _, page in source.searched)
    assert calls == len(theme.keywords)
    # 45 日より先（11/14 のカンファレンス）は窓の外
    titles = {c.event.title for c in candidates}
    assert "Tokyo Frontend Conference 2026" not in titles
    assert "Python もくもく会 in 梅田 #42" in titles


@pytest.mark.asyncio
async def test_theme_run_saves_meetups_to_the_pool(store_backend):
    run, started = await run_theme_collection(theme_by_id("meetup-study"), now=FROZEN_NOW)
    assert started
    saved = [e for e in store_backend.list_events() if e.kind == "meetup"]
    assert saved and all(e.theme_id == "meetup-study" for e in saved)
    # 締切が分からないので partial。表示はされる（§6.6）
    assert {e.validation_status for e in saved} == {"partial"}
    assert any(e.kind == "meetup" for e in pool_candidates(now=FROZEN_NOW))


def test_demo_rows_are_valid_listings():
    assert all(listing_from_json(row) is not None for row in DEMO_ROWS)
