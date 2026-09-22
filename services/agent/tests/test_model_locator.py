"""モデルは行を引用するだけで、値は決定論的に決まる（extraction/model_locator）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from event_agent.clients import gemini
from event_agent.clients.page_fetcher import FetchedPage
from event_agent.extraction.model_locator import candidate_from_lines, extract_with_model
from event_agent.extraction.sources import source_type_for
from event_agent.security.prompt_guard import canary

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 21, 9, 0, tzinfo=JST)

HTML = """<html><body>
<h1>関西 AI Builders Night</h1>
<p>2026年に開催する、生成AIを手を動かして学ぶ夜のミートアップです。</p>
<p>日時：2026年10月20日（火）19:00〜21:00</p>
<p>参加申込は 2026年10月15日 まで受け付けます。</p>
<p>早割申込締切: 2026年10月1日</p>
<p>場所：梅田スカイビル タワーイースト</p>
<p>運営: AI Builders Kansai</p>
</body></html>"""


def page(body: str = HTML, url: str = "https://ai-builders.example.jp/night") -> FetchedPage:
    return FetchedPage(
        requested_url=url, final_url=url, status_code=200,
        content_type="text/html", text=body, byte_length=len(body),
        content_hash="f" * 64, fetched_at=NOW,
    )


def fake_model(monkeypatch, reply: str | None):
    async def generate_text(prompt: str, system: str | None = None) -> str | None:
        assert "UNTRUSTED_PAGE" in prompt
        return reply

    monkeypatch.setattr(gemini.gemini_client, "generate_text", generate_text)


@pytest.mark.asyncio
async def test_verbatim_quotes_become_a_candidate(monkeypatch):
    fake_model(monkeypatch, json.dumps({
        "title": "関西 AI Builders Night",
        "eventDateLine": "日時：2026年10月20日（火）19:00〜21:00",
        "deadlineLine": "参加申込は 2026年10月15日 まで受け付けます。",
        "venueLine": "場所：梅田スカイビル タワーイースト",
        "organizerLine": "運営: AI Builders Kansai",
    }))
    got = await extract_with_model(page(), hit=None, run_id="run", now=NOW, user_id="u", source_type="official")
    assert got is not None
    e = got.event
    assert e.title == "関西 AI Builders Night"
    assert e.dates.event_start == datetime(2026, 10, 20, 19, 0, tzinfo=JST)
    assert e.dates.application_deadline == datetime(2026, 10, 15, tzinfo=JST)
    assert e.dates.application_deadline_precision == "date"
    assert e.location.venue and "梅田スカイビル" in e.location.venue
    assert e.organizer == "運営: AI Builders Kansai"
    supported = {f for ev in got.evidence for f in ev.supports}
    assert {"title", "dates.eventStart", "dates.applicationDeadline", "location", "organizer"} <= supported
    # 根拠の抜粋はページの引用そのもの
    assert all(ev.source_url == "https://ai-builders.example.jp/night" for ev in got.evidence)


@pytest.mark.asyncio
async def test_fabricated_quote_is_dropped(monkeypatch):
    # 本文に無い締切をモデルが作っても採用しない。開催日は本文の引用なので通る
    fake_model(monkeypatch, json.dumps({
        "title": "関西 AI Builders Night",
        "eventDateLine": "日時：2026年10月20日（火）19:00〜21:00",
        "deadlineLine": "申込締切: 2026年10月18日 23:59",
        "venueLine": None, "organizerLine": None,
    }))
    got = await extract_with_model(page(), hit=None, run_id="run", now=NOW, user_id="u")
    assert got is not None
    assert got.event.dates.application_deadline is None
    assert got.event.dates.application_deadline_precision == "unknown"


@pytest.mark.asyncio
async def test_early_bird_line_is_not_a_deadline(monkeypatch):
    fake_model(monkeypatch, json.dumps({
        "title": "関西 AI Builders Night",
        "eventDateLine": "日時：2026年10月20日（火）19:00〜21:00",
        "deadlineLine": "早割申込締切: 2026年10月1日",
        "venueLine": None, "organizerLine": None,
    }))
    got = await extract_with_model(page(), hit=None, run_id="run", now=NOW, user_id="u")
    assert got is not None and got.event.dates.application_deadline is None


def test_year_is_never_inferred_from_a_quote():
    body = HTML.replace("2026年10月20日（火）", "10月20日（火）").replace("2026年に開催する", "2025年に続き2027年も予定")
    lines = {"title": "関西 AI Builders Night", "eventDateLine": "日時：10月20日（火）19:00〜21:00",
             "deadlineLine": None, "venueLine": None, "organizerLine": None}
    assert candidate_from_lines(page(body), lines, hit=None, run_id="run", now=NOW, user_id="u") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [None, "わかりません", "```json\n{\"title\": 1}\n```"])
async def test_unusable_replies_give_no_candidate(monkeypatch, reply):
    fake_model(monkeypatch, reply)
    assert await extract_with_model(page(), hit=None, run_id="run", now=NOW, user_id="u") is None


@pytest.mark.asyncio
async def test_canary_leak_is_discarded(monkeypatch):
    fake_model(monkeypatch, json.dumps({"title": canary(), "eventDateLine": "日時：2026年10月20日（火）19:00〜21:00"}))
    assert await extract_with_model(page(), hit=None, run_id="run", now=NOW, user_id="u") is None


def test_source_type_for_classifies_hosts():
    assert source_type_for("https://connpass.com/event/1/") == "aggregator"
    assert source_type_for("https://osaka.connpass.com/event/1/") == "aggregator"
    assert source_type_for("https://example.org/event") == "official"
    assert source_type_for("https://agentic.example.jp/meetup/12", {"https://agentic.example.jp/meetup/12": "organizer"}) == "organizer"
