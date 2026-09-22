"""補助金を jGrants の公開 API から作る（ADR-011 / ジャンル拡張計画 段階4）。

Web 収集と違い抽出が無いので、確かめるのは写し替えと収集の作法:
UTC の締切を JST にする、公募が終わったものを載せない、実施日を作らない、
API の呼び出し回数を抑える。ネットワークには出ない（デモデータを使う）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from conftest import FROZEN_NOW
from event_agent.clients.jgrants import listing_from_json, public_page_url
from event_agent.demo.subsidies import DemoSubsidySource
from event_agent.workflows.collect import run_theme_collection
from event_agent.workflows.subsidies import collect_subsidies, event_from_subsidy
from event_agent.workflows.themes import theme_by_id

JST = timezone(timedelta(hours=9))


def test_utc_deadline_becomes_jst_without_guessing():
    """API は UTC で返す。14:59Z は JST 23:59。ずれると締切を 1 日間違える。"""
    listing = listing_from_json(
        {
            "id": "a0W",
            "title": "テスト補助金",
            "acceptance_end_datetime": "2026-10-30T14:59:00.000Z",
            "acceptance_start_datetime": "2026-09-01T00:00:00.000Z",
        }
    )
    assert listing is not None
    assert listing.acceptance_end.isoformat() == "2026-10-30T23:59:00+09:00"
    assert listing.acceptance_start.isoformat() == "2026-09-01T09:00:00+09:00"

    # 読めない日時は推測しない（§6.5）
    broken = listing_from_json({"id": "a", "title": "t", "acceptance_end_datetime": "未定"})
    assert broken is not None and broken.acceptance_end is None


def test_event_has_a_deadline_but_no_event_date():
    listing = listing_from_json(
        {
            "id": "demo-subsidy-0001",
            "title": "大阪府 中小企業スタートアップ支援補助金",
            "institution_name": "大阪府",
            "subsidy_max_limit": 3000000,
            "target_area_search": "大阪府",
            "acceptance_start_datetime": "2026-09-01T00:00:00.000Z",
            "acceptance_end_datetime": "2026-11-27T14:59:00.000Z",
        }
    )
    got = event_from_subsidy(listing, None, now=FROZEN_NOW, run_id="r")
    assert got is not None
    event, evidence = got
    assert event.kind == "subsidy" and event.category == "subsidy"
    assert event.dates.event_start is None
    assert event.dates.application_deadline.isoformat() == "2026-11-27T23:59:00+09:00"
    assert [m.label for m in event.dates.milestones] == ["受付開始"]
    assert event.attributes["上限額"] == "3,000,000円"
    assert event.attributes["対象地域"] == "大阪府"
    # 根拠は API の値そのもの。出典は jGrants の公開ページ
    assert {tuple(e.supports) for e in evidence} == {("title",), ("dates.applicationDeadline",)}
    assert all(e.source_url == public_page_url(None, "demo-subsidy-0001") for e in evidence)

    # 締切が読めない補助金は載せない（締切を作らない）
    undated = listing_from_json({"id": "x", "title": "締切未定の補助金"})
    assert event_from_subsidy(undated, None, now=FROZEN_NOW, run_id="r") is None


@pytest.mark.asyncio
async def test_collection_skips_closed_calls_and_limits_detail_requests():
    theme = theme_by_id("subsidy-startup")
    source = DemoSubsidySource()
    candidates, calls = await collect_subsidies(
        theme, run_id="r", now=FROZEN_NOW, source=source
    )
    titles = [c.event.title for c in candidates]
    assert "大阪府 中小企業スタートアップ支援補助金" in titles
    # 公募が終わったものは入らない
    assert all("事業再構築補助金" not in title for title in titles)
    assert source.searched == list(theme.keywords)
    assert calls == len(theme.keywords) + len(candidates)

    # 詳細の上限を超えた分は一覧の値だけで載せる（レート制限を守る）
    few, _ = await collect_subsidies(
        theme, run_id="r", now=FROZEN_NOW, source=DemoSubsidySource(), detail_limit=0
    )
    assert few and all("補助率" not in c.event.attributes for c in few)


@pytest.mark.asyncio
async def test_area_filter_keeps_national_and_the_region(store_backend):
    kansai = theme_by_id("subsidy-kansai")
    candidates, _ = await collect_subsidies(
        kansai, run_id="r", now=FROZEN_NOW, source=DemoSubsidySource()
    )
    areas = {c.event.attributes.get("対象地域") for c in candidates}
    assert areas <= {"大阪府", "全国"}


@pytest.mark.asyncio
async def test_theme_run_saves_subsidies_without_search(store_backend, monkeypatch):
    """補助金テーマは Grounding を使わない。検索回数は 0 のまま。"""
    from event_agent.workflows import subsidies

    monkeypatch.setattr(subsidies, "_source", DemoSubsidySource())
    run, started = await run_theme_collection(theme_by_id("subsidy-dx"), now=FROZEN_NOW)
    assert started and run.status in ("succeeded", "partial_success")
    assert run.grounding_calls == 0 and run.model_calls == 0
    saved = [e for e in store_backend.list_events() if e.kind == "subsidy"]
    assert saved and all(e.dates.event_start is None for e in saved)
    assert all(e.theme_id == "subsidy-dx" for e in saved)
