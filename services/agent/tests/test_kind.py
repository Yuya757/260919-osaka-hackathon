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

    def test_milestone_label_comes_from_the_line(self):
        """ラベル表は部分一致なので、行の見出しを名前に使う。

        「一次審査結果発表」を「一次審査」と出すと、審査の日と発表の日が
        入れ替わって見える。
        """
        text = "一次審査結果発表: 2026年12月18日\n■ 最終審査会 2027年2月6日"
        got = d.find_milestones(text, fallback_year=None, kind="contest")
        assert [label for label, _ in got] == ["一次審査結果発表", "最終審査会"]

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


# ---- 段階2: アクセラ・共創（事前調査 2026-09-22 に AUBA と Creww の実ページで確認）

# Creww Growth のプログラムページの書き方。締切は「募集期間」の終わり
CREWW_HTML = """<html><body>
<h1>ANA Xオープンイノベーションプログラム2026(秋)</h1>
<p>ANAグループのプラットフォーム事業会社として、新規事業の共創パートナーを募集します。</p>
<p>募集期間：2026年 9月 14日～10月 4日</p>
<p>選考期間：2026年 10月 5日～10月 30日</p>
<p>面談期間：2026年 11月以降順次実施</p>
</body></html>"""

# AUBA（eiicon）の公募プログラム。実施日は書かれず、締切だけがある
AUBA_HTML = """<html><body>
<h1>【青森県2026】ヤマモト食品株式会社 - プログラム応募</h1>
<p>応募期間</p>
<p>2026年09月09日〜2026年10月18日</p>
<p>■応募締切：2026年10月18日（日）23:59まで</p>
<p>10月29日に青森市内で開催されるワークショップへの参加が必須です。</p>
</body></html>"""


class TestProgramGenres:
    def test_period_labels_give_the_end_as_the_deadline(self):
        """「募集期間 A〜B」は B が締切。開始日を締切にすると応募できるものが終了に見える。"""
        got = extract_candidate(
            page(CREWW_HTML), hit=None, run_id="r", now=NOW, user_id="u", kind="accelerator"
        )
        assert got is not None
        e = got.event
        assert e.kind == "accelerator"
        assert e.dates.application_deadline.date().isoformat() == "2026-10-04"
        assert ("選考期間", "2026-10-05") in [
            (m.label, m.at.date().isoformat()) for m in e.dates.milestones
        ]

    def test_cocreation_without_an_event_date_is_kept(self):
        got = extract_candidate(
            page(AUBA_HTML), hit=None, run_id="r", now=NOW, user_id="u", kind="cocreation"
        )
        assert got is not None
        e = got.event
        assert e.dates.event_start is None
        assert e.dates.application_deadline.isoformat() == "2026-10-18T23:59:00+09:00"
        # ページはジャンルを名乗っていない。本文の「ワークショップ」で分類しない
        assert got.headline_kind is None
        assert e.category == "cocreation"

    def test_bare_deadline_label_is_a_last_resort(self):
        """一覧ページの「締切2026.09.27」のような書き方も読む。"""
        line = "締切2026.09.27"
        got = d.find_application_deadline(line, fallback_year=None, kind="accelerator")
        assert got is not None and got.value.date().isoformat() == "2026-09-27"
        # ラベルが具体的なときはそちらが勝つ（早期申込は締切ではない）
        early = "早期申込締切: 2026年9月30日"
        assert d.find_application_deadline(early, fallback_year=None, kind="accelerator") is None

    def test_headline_kind_only_reads_the_title(self):
        from event_agent.extraction.extractor import headline_kind

        assert headline_kind("生成AIハッカソン 2026") == "hackathon"
        assert headline_kind("Kansai Accelerator Program") == "accelerator"
        assert headline_kind("ANA Xオープンイノベーションプログラム2026") == "cocreation"
        # 名乗っていないタイトルでは判定しない（本文の一語で決めない）
        assert headline_kind("【青森県2026】ヤマモト食品株式会社 - プログラム応募") is None


def test_theme_gate_drops_only_confident_mismatches():
    """テーマのゲートは見出しで名乗っているときだけ落とす（ADR-008）。"""
    from event_agent.extraction.extractor import ExtractedCandidate
    from event_agent.workflows.collect import _gate_categories

    def candidate(kind: str | None) -> ExtractedCandidate:
        got = extract_candidate(
            page(AUBA_HTML), hit=None, run_id="r", now=NOW, user_id="u", kind="cocreation"
        )
        assert got is not None
        got.headline_kind = kind
        return got

    notes: list[str] = []

    def note(agent: str, message: str, *, level: str = "info") -> None:
        notes.append(message)

    kept, dropped = _gate_categories(
        [candidate("hackathon"), candidate(None), candidate("cocreation")],
        ("cocreation", "accelerator"),
        note,
    )
    assert len(kept) == 2 and dropped == 1
    assert notes and "対象ジャンル外" in notes[0]


class TestAttributes:
    """ジャンル固有の値（ジャンル拡張計画 段階2）。構造化せず行のまま持つ。"""

    def test_program_attributes_are_picked_by_label(self):
        html = """<html><body><h1>Kansai Accelerator Program 2026</h1>
        <p>応募締切: 2026年10月20日</p>
        <p>支援内容: メンタリングと実証フィールドの提供</p>
        <p>対象ステージ: シード〜シリーズA</p>
        <p>出資: 最大1,000万円</p>
        <p>支援内容については別途ご説明します。</p>
        </body></html>"""
        got = extract_candidate(
            page(html), hit=None, run_id="r", now=NOW, user_id="u", kind="accelerator"
        )
        assert got is not None
        assert got.event.attributes == {
            "支援内容": "メンタリングと実証フィールドの提供",
            "対象ステージ": "シード〜シリーズA",
            "出資": "最大1,000万円",
        }

    def test_sentences_and_longer_labels_are_not_values(self):
        text = "対象ステージ: シード\n賞金については後日お知らせします。\n参加費: 無料"
        # ハッカソンの表に「対象ステージ」は無い。「対象」で途中から拾わない
        assert d.find_attributes(text, kind="hackathon") == {"参加費": "無料"}

    def test_attributes_stay_within_the_contract(self):
        from event_agent.schemas import ApiEvent

        event = ApiEvent(
            eventId="e", title="t", category="contest", summary="",
            location={"type": "online"}, dates=EventDates(),
            officialUrl="https://example.jp/e",
            attributes={f"k{i}": "v" * 80 for i in range(12)},
        )
        assert len(event.attributes) == 10
        assert all(len(v) == 60 for v in event.attributes.values())


class TestNearestStation:
    """最寄駅の抽出（経路検索の到着駅に使う）。

    実データではラベル行（最寄駅: …）が無い告知の方が多く、最寄駅が取れないと
    経路検索が会場名を駅名として送ってしまい「駅が見つかりません」になっていた。
    """

    def test_labelled_and_unlabelled_access_lines(self):
        from event_agent.extraction.extractor import station_of

        assert station_of("アクセス: JR大阪駅から徒歩5分") == "大阪"
        assert station_of("会場: QUINTBRIDGE\n京阪電車「京橋」駅より徒歩5分") == "京橋"
        assert station_of("最寄駅: Osaka Metro御堂筋線本町駅 3番出口から徒歩2分") == "本町"
        assert station_of("交通: 阪急「梅田」駅 直結") == "梅田"

    def test_unrelated_sentences_do_not_become_stations(self):
        from event_agent.extraction.extractor import station_of

        # アクセスの話ではない行から駅名を拾わない（推測しない）
        assert station_of("大阪駅前の再開発をテーマにしたハッカソンです。") is None
        assert station_of("各駅停車でお越しください") is None
        assert station_of("会場: グランフロント大阪") is None
