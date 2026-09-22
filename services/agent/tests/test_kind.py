"""kind の導入（ジャンル拡張計画 段階1）。

事前調査で見つかった 2 つのジャンル差と 2 つの不具合を検証する:
「提出締切」の意味が kind で反転する／実施日が無い告知を落とさない／
範囲締切は終わりを採る／まとめ記事サイトを候補にしない。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from event_agent.clients.page_fetcher import FetchedPage
from event_agent.extraction import dates as d
from event_agent.extraction.extractor import category_of, extract_candidate, kind_of
from event_agent.extraction.model_locator import candidate_from_lines
from event_agent.extraction.sources import is_article_host, source_type_for
from event_agent.schemas import EventDates, EventMilestone

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 21, 9, 0, tzinfo=JST)


def page(body: str, url: str = "https://example.jp/contest") -> FetchedPage:
    return FetchedPage(
        requested_url=url, final_url=url, status_code=200, content_type="text/html",
        text=body, byte_length=len(body.encode()), content_hash="c" * 64, fetched_at=NOW,
    )


CONTEST_HTML = """<html><body>
<h1>第14回 高校生ビジネスプラン・グランプリ</h1>
<p>高校生のビジネスプランを募集します。書類審査を経て最終審査会を行います。</p>
<p>ビジネスプランシート応募・提出締切: 2026年9月24日</p>
<p>一次選考通過: 2026年11月5日</p>
<p>最終審査会: 2027年1月10日</p>
<p>主催: 日本政策金融公庫</p>
</body></html>"""


class TestKindMapping:
    def test_category_and_kind(self):
        assert category_of("高校生ビジネスプラン・グランプリ") == "contest"
        assert category_of("生成AIハッカソン") == "hackathon"
        assert kind_of("contest") == "contest" and kind_of("pitch") == "contest"
        assert kind_of("acceleration") == "accelerator"
        assert kind_of("meetup") == "hackathon"  # 既定


class TestLabelSets:
    def test_submission_deadline_flips_by_kind(self):
        """事前調査 1: 「提出締切」はハッカソンでは除外、ビジコンでは本物の応募締切。"""
        line = "ビジネスプランシート応募・提出締切、必着: 2026年9月24日"
        assert d.find_application_deadline(line, fallback_year=None, kind="hackathon") is None
        got = d.find_application_deadline(line, fallback_year=None, kind="contest")
        assert got is not None and got.value.date().isoformat() == "2026-09-24"
        # 早割はどちらでも締切にしない
        early = "早期申込締切: 2026年8月1日"
        for kind in ("hackathon", "contest"):
            assert d.find_application_deadline(early, fallback_year=None, kind=kind) is None

    def test_range_deadline_takes_the_end(self):
        """事前調査の不具合 1: 「募集期間 A〜B締切」は終わりが締切。"""
        line = "募集締切: 2026年6月4日(木)~2026年8月6日(木)13:00"
        got = d.find_application_deadline(line, fallback_year=None, kind="contest")
        assert got is not None and got.value.date().isoformat() == "2026-08-06"
        assert d.deadline_from_fragment("2026年9月24日", fallback_year=None).value.day == 24

    def test_milestones_are_collected(self):
        text = "一次選考通過: 2026年11月5日\n最終審査会: 2027年1月10日\n結果発表: 2027年1月20日"
        got = d.find_milestones(text, fallback_year=None, kind="contest")
        assert [label for label, _ in got] == ["一次選考通過", "最終審査会", "結果発表"]
        assert [p.value.year for _, p in got] == [2026, 2027, 2027]


class TestOptionalEventStart:
    def test_contest_without_event_date_is_kept(self):
        """事前調査 2: 締切だけ分かるビジコンを落とさない。"""
        html = CONTEST_HTML.replace("<p>最終審査会: 2027年1月10日</p>", "<p>結果発表は11月下旬</p>")
        got = extract_candidate(page(html), hit=None, run_id="r", now=NOW, user_id="u", kind="contest")
        assert got is not None
        assert got.event.dates.event_start is None
        assert got.event.dates.event_start_precision == "unknown"
        assert got.event.dates.application_deadline.date().isoformat() == "2026-09-24"
        assert got.event.kind == "contest"
        assert "dates.eventStart" not in {ev.supports[0] for ev in got.evidence}

    def test_hackathon_still_requires_an_event_date(self):
        html = """<html><body><h1>生成AIハッカソン</h1>
        <p>申込締切: 2026年9月24日</p></body></html>"""
        assert extract_candidate(page(html), hit=None, run_id="r", now=NOW, user_id="u") is None

    def test_contest_with_dates_and_milestones(self):
        got = extract_candidate(page(CONTEST_HTML), hit=None, run_id="r", now=NOW, user_id="u", kind="contest")
        assert got is not None
        e = got.event
        assert e.kind == "contest"
        assert e.dates.event_start.date().isoformat() == "2027-01-10"  # 最終審査会
        assert e.dates.application_deadline.date().isoformat() == "2026-09-24"
        assert [m.label for m in e.dates.milestones] == ["一次選考通過", "最終審査会"]

    def test_quote_extraction_keeps_contest_without_event_date(self):
        lines = {
            "title": "第14回 高校生ビジネスプラン・グランプリ",
            "eventDateLine": None,
            "deadlineLine": "ビジネスプランシート応募・提出締切、必着: 2026年9月24日",
            "venueLine": None,
            "organizerLine": "主催: 日本政策金融公庫",
        }
        got = candidate_from_lines(
            page(CONTEST_HTML), lines, hit=None, run_id="r", now=NOW, user_id="u", kind="contest"
        )
        assert got is not None and got.event.dates.event_start is None
        assert got.event.dates.application_deadline.date().isoformat() == "2026-09-24"
        # 同じ引用でもハッカソンなら締切として採らない → 候補にもならない
        assert candidate_from_lines(
            page(CONTEST_HTML), lines, hit=None, run_id="r", now=NOW, user_id="u", kind="hackathon"
        ) is None


class TestSources:
    def test_article_and_aggregator_hosts(self):
        assert is_article_host("https://www.startuplist.jp/alliance_posts/110")
        assert source_type_for("https://compe.japandesign.ne.jp/x/") == "aggregator"
        assert source_type_for("https://www.craftstadium.com/hackathon/x") == "official"


class TestDatesModel:
    def test_dedup_key_falls_back_to_the_deadline(self):
        from event_agent.domain.normalize import compute_dedup_key

        with_start = compute_dedup_key("https://e.jp/a", "t", datetime(2027, 1, 10, tzinfo=JST), "o")
        only_deadline = compute_dedup_key(
            "https://e.jp/a", "t", None, "o", datetime(2026, 9, 24, tzinfo=JST)
        )
        nothing = compute_dedup_key("https://e.jp/a", "t", None, "o")
        assert len({with_start, only_deadline, nothing}) == 3

    def test_precision_is_unknown_without_a_start(self):
        dates = EventDates(applicationDeadline=datetime(2026, 9, 24, tzinfo=JST))
        assert dates.event_start is None and dates.event_start_precision == "unknown"
        assert dates.milestones == []
        withm = EventDates(
            eventStart=datetime(2027, 1, 10, tzinfo=JST),
            milestones=[EventMilestone(label="結果発表", at=datetime(2027, 1, 20, tzinfo=JST))],
        )
        assert withm.event_start_precision == "datetime" and withm.milestones[0].precision == "date"
