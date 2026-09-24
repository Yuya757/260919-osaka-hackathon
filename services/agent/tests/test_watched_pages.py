"""利用者が登録したページ（ADR-014）。

確かめること: 登録したページがイベントになって共有プールに出る、同じページは二度
登録しない、robots.txt・http・私設アドレス・開催日の無いページは断る、回数を抑える、
毎朝の見守りは内容が変わったページだけ読み直し、変わらなければ見た印だけ進め、
3 回続けて読めなければ止める。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import FROZEN_NOW
from event_agent.clients import robots
from event_agent.clients.page_fetcher import FixturePage, FixturePageSource, page_fetcher
from event_agent.workflows import watched_pages
from event_agent.workflows.pool import candidates
from event_agent.workflows.watched_pages import register_page, watch_all

URL = "https://hack.example.jp/kansai-2026"
HACKATHON = """<html><head><title>関西 生成AI ハッカソン 2026</title></head><body>
<h1>関西 生成AI ハッカソン 2026</h1>
<p>生成AIでプロダクトを作る2日間のハッカソンです。</p>
<div>開催日時: 2026年10月17日 10:00〜10月18日 18:00</div>
<div>申込締切: 2026年10月10日 23:59</div>
<div>会場: グランフロント大阪</div>
<div>主催: 関西AIコミュニティ</div>
</body></html>"""


@pytest.fixture
def pages(monkeypatch):
    """登録用のページ。テストの中で書き換えられるよう dict を返す。"""
    robots.clear_cache()
    table = {
        URL: FixturePage(body=HACKATHON),
        "https://blocked.example.jp/robots.txt": FixturePage(
            body="User-agent: *\nDisallow: /", content_type="text/plain"
        ),
        "https://blocked.example.jp/event": FixturePage(body=HACKATHON),
        "https://nodate.example.jp/about": FixturePage(
            body="<html><head><title>会社概要</title></head><body><h1>会社概要</h1></body></html>"
        ),
    }
    monkeypatch.setattr(page_fetcher, "_source", FixturePageSource(table))
    yield table
    robots.clear_cache()


@pytest.mark.asyncio
async def test_registered_page_becomes_a_pooled_event(store_backend, pages):
    result = await register_page(URL, "s1", now=FROZEN_NOW)
    assert result.status == "added", result.message
    assert result.event and result.event.title.startswith("関西 生成AI ハッカソン")
    assert result.event.dates.application_deadline is not None
    assert result.event.theme_id == "user-registered"
    assert any(e.event_id == result.event.event_id for e in candidates(now=FROZEN_NOW))
    # エージェントの動きが残っている（画面に流す）
    assert any("ページを読みました" in line.message for line in result.activity)

    again = await register_page(URL + "/", "s1", now=FROZEN_NOW)
    assert again.status == "exists"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://hack.example.jp/kansai-2026", "bad_url"),
        ("https://127.0.0.1/event", "bad_url"),
        ("https://blocked.example.jp/event", "robots"),
        ("https://missing.example.jp/event", "unavailable"),
        ("https://nodate.example.jp/about", "no_event"),
    ],
)
async def test_refuses_pages_it_must_not_or_cannot_use(store_backend, pages, url, reason):
    result = await register_page(url, "s1", now=FROZEN_NOW)
    assert result.status == "rejected" and result.reason == reason


@pytest.mark.asyncio
async def test_registrations_are_capped_per_session(store_backend, pages):
    for index in range(watched_pages.PER_SESSION_DAILY):
        pages[f"https://many.example.jp/{index}"] = FixturePage(body=HACKATHON.replace("2026", "2026", 1))
        await register_page(f"https://many.example.jp/{index}", "s2", now=FROZEN_NOW)
    capped = await register_page(URL, "s2", now=FROZEN_NOW)
    assert capped.status == "rejected" and capped.reason == "quota"
    # 別のセッションは使える
    assert (await register_page(URL, "s3", now=FROZEN_NOW)).status == "added"


@pytest.mark.asyncio
async def test_daily_watch_rereads_only_changed_pages(store_backend, pages):
    added = await register_page(URL, "s1", now=FROZEN_NOW)
    event_id = added.event.event_id

    # 翌日: 内容が同じなら読み直さず、見た印だけ進める
    day2 = FROZEN_NOW + timedelta(days=1)
    changed, unchanged, started = await watch_all(now=day2)
    assert (changed, unchanged, started) == (0, 1, True)
    assert store_backend.get_event(event_id).last_seen_at == day2
    # 同じ日に二度は走らない
    assert (await watch_all(now=day2))[2] is False

    # 3 日目: 締切が延びた → 読み直して反映する
    pages[URL] = FixturePage(body=HACKATHON.replace("10月10日 23:59", "10月14日 23:59"))
    day3 = FROZEN_NOW + timedelta(days=2)
    changed, unchanged, _ = await watch_all(now=day3)
    assert changed == 1
    deadlines = {
        e.dates.application_deadline.day
        for e in store_backend.list_recent_events(FROZEN_NOW)
        if e.title.startswith("関西 生成AI ハッカソン")
    }
    assert 14 in deadlines


@pytest.mark.asyncio
async def test_watch_stops_after_three_failures(store_backend, pages):
    await register_page(URL, "s1", now=FROZEN_NOW)
    del pages[URL]
    for day in range(1, 4):
        await watch_all(now=FROZEN_NOW + timedelta(days=day))
    assert store_backend.list_watched_pages() == []
