"""テーマ単位の定期収集（ADR-008）。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import FROZEN_NOW
from event_agent.config import get_settings
from event_agent.entrypoints.job import select_themes
from event_agent.workflows.collect import run_theme_collection, scheduled_idempotency_key
from event_agent.workflows.themes import COLLECTION_THEMES, theme_by_id, theme_for_task_index


def test_themes_map_to_task_indices():
    assert [t.id for t in COLLECTION_THEMES] == [
        "hackathon-kansai", "hackathon-kanto", "hackathon-chubu", "hackathon-online",
        "contest-kansai", "contest-kanto", "contest-online",
    ]
    assert theme_for_task_index(3).id == "hackathon-online"
    assert theme_for_task_index(6).id == "contest-online"
    # 止めているテーマはタスクに割り当てないが、id では引ける
    assert "subsidy-kansai" not in {t.id for t in COLLECTION_THEMES}
    assert theme_by_id("subsidy-kansai").kind == "subsidy"
    with pytest.raises(ValueError):
        theme_for_task_index(len(COLLECTION_THEMES))
    assert theme_by_id("hackathon-kanto").locations == ("関東", "東京")
    assert select_themes(["job"], {"CLOUD_RUN_TASK_INDEX": "2"})[0].id == "hackathon-chubu"
    assert select_themes(["job", "contest-kansai"], {})[0].id == "contest-kansai"
    assert len(select_themes(["job"], {})) == len(COLLECTION_THEMES)


def test_contest_themes_target_contest_kind_and_sites():
    theme = theme_by_id("contest-kansai")
    assert theme.kind == "contest" and theme.allowed_kinds == ("contest",)
    # ビジコンは connpass ではなく公募情報サイトと主催者のページに集まる
    joined = " ".join(theme.site_queries)
    assert "koubo.jp" in joined and "connpass" not in joined
    assert "go.jp" in joined  # 自治体


def test_program_themes_target_the_platforms():
    """アクセラ・共創は AUBA と Creww に集まる（事前調査 2026-09-22）。"""
    accelerator = theme_by_id("accelerator-kansai")
    assert accelerator.kind == "accelerator"
    # 共創プログラムはアクセラと同じ場所に載るので、どちらも残す
    assert set(accelerator.allowed_kinds) == {"accelerator", "cocreation"}
    assert "creww.me" in " ".join(accelerator.site_queries)
    cocreation = theme_by_id("cocreation-kanto")
    assert cocreation.kind == "cocreation"
    assert "auba.eiicon.net" in " ".join(cocreation.site_queries)


def test_query_plan_differs_by_kind():
    from datetime import timezone as _tz

    from event_agent.workflows.collect import _plan_queries

    now = FROZEN_NOW.astimezone(_tz.utc)
    contest = theme_by_id("contest-kansai")
    hackathon = theme_by_id("hackathon-kansai")
    assert "応募 締切" in _plan_queries(contest.preferences(now=now), contest)[0]
    assert "イベント 申込" in _plan_queries(hackathon.preferences(now=now), hackathon)[0]
    accelerator = theme_by_id("accelerator-online")
    assert "募集 締切" in _plan_queries(accelerator.preferences(now=now), accelerator)[0]
    # テーマ無し（手動 Run）は従来どおりハッカソン向けのサイト指名
    assert "connpass" in " ".join(_plan_queries(hackathon.preferences(now=now)))


def test_theme_key_is_daily_and_distinct_from_user_keys():
    kansai = scheduled_idempotency_key("theme:hackathon-kansai", now=FROZEN_NOW, schedule_version="v")
    assert kansai == scheduled_idempotency_key(
        "theme:hackathon-kansai", now=FROZEN_NOW + timedelta(hours=5), schedule_version="v"
    )
    assert kansai != scheduled_idempotency_key("theme:hackathon-kanto", now=FROZEN_NOW, schedule_version="v")
    assert kansai != scheduled_idempotency_key("demo-user", now=FROZEN_NOW, schedule_version="v")
    assert kansai != scheduled_idempotency_key(
        "theme:hackathon-kansai", now=FROZEN_NOW + timedelta(days=1), schedule_version="v"
    )


@pytest.mark.asyncio
async def test_theme_run_collects_once_a_day_and_skips_known_pages(store_backend):
    theme = theme_by_id("hackathon-kansai")
    first, started = await run_theme_collection(theme, now=FROZEN_NOW)
    assert started and first.theme_id == "hackathon-kansai" and first.user_id == "system"
    assert first.skipped_known_count == 0
    events = store_backend.list_events(first.run_id)
    assert events
    # 共有プール向け: 特定ユーザーの点数を書かない。抽出時刻とテーマを持つ
    assert all(e.recommendation is None for e in events)
    assert all(e.last_extracted_at == FROZEN_NOW and e.theme_id == "hackathon-kansai" for e in events)

    again, started_again = await run_theme_collection(theme, now=FROZEN_NOW + timedelta(hours=2))
    assert not started_again and again.run_id == first.run_id

    # 翌日: 同じページは抽出を省き、lastSeenAt だけ進む
    tomorrow = FROZEN_NOW + timedelta(days=1)
    second, _ = await run_theme_collection(theme, now=tomorrow)
    assert second.run_id != first.run_id
    assert second.skipped_known_count == len(events)
    assert second.status in ("succeeded", "partial_success")
    for before in events:
        after = store_backend.get_event(before.event_id)
        assert after.last_seen_at == tomorrow
        assert after.last_extracted_at == FROZEN_NOW
        assert after.source_run_id == first.run_id
    assert any(
        line.agent == "extractor" and "最近抽出済み" in line.message for line in second.activity
    )

    # 8 日後: 鮮度切れなので抽出し直す
    later = FROZEN_NOW + timedelta(days=8)
    third, _ = await run_theme_collection(theme, now=later)
    assert third.skipped_known_count == 0
    assert all(
        store_backend.get_event(e.event_id).last_extracted_at == later for e in events
    )


@pytest.mark.asyncio
async def test_daily_grounding_cap_ends_the_run_as_partial_success(store_backend, monkeypatch):
    from event_agent.clients import gemini

    # デモモードでは検索が無料なので上限を見ない。本番と同じ分岐を通す
    monkeypatch.setattr(gemini.gemini_client, "_client", object())
    monkeypatch.setattr(get_settings(), "daily_grounding_cap", 2)
    monkeypatch.setattr(get_settings(), "demo_catalog_fallback", False)
    theme = theme_by_id("hackathon-online")
    run, _ = await run_theme_collection(theme, now=FROZEN_NOW)
    assert run.status == "partial_success"
    assert run.grounding_calls == 0 and run.candidate_count == 0
    assert any(line.level == "warn" and "検索上限" in line.message for line in run.activity)
    assert store_backend.get_usage("2026-09-21") is None


def test_task_count_matches_the_deployed_job():
    """Cloud Run Job の --tasks はテーマ数と一致していなければならない。

    ずれるとテーマが収集されない（少ない）か、範囲外でタスクが失敗する（多い）。
    """
    import pathlib
    import re

    workflow = pathlib.Path(__file__).resolve().parents[3] / ".github/workflows/deploy-develop.yml"
    match = re.search(r"--tasks (\d+)", workflow.read_text(encoding="utf-8"))
    assert match, "deploy-develop.yml に --tasks が見つからない"
    assert int(match.group(1)) == len(COLLECTION_THEMES)


@pytest.mark.asyncio
async def test_collection_fills_nearest_station_from_the_address(store_backend, monkeypatch):
    """会場が住所のイベントは、収集時に最寄駅まで入れておく。

    入れておけば一覧にも詳細にも出て、経路検索が到着駅の入力なしで動く。
    駅すぱあとが使えないときは何もしない（収集自体は続ける）。
    """
    from event_agent.clients.ekispert import Station
    from event_agent.schemas import EventLocation, UserPreferences
    from event_agent.workflows import collect as collect_module

    asked: list[str] = []

    class FakeEkispert:
        configured = True

        async def find_station_near_address(self, address: str, **_: object) -> Station | None:
            asked.append(address)
            return Station(code="22828", name="京橋(大阪府)") if "都島区" in address else None

    monkeypatch.setattr(collect_module, "ekispert_client", FakeEkispert())

    events = [
        e.model_copy(
            update={
                "location": EventLocation(
                    type="offline", venue="大阪市都島区東野田町4丁目15番82号", region="大阪"
                )
            }
        )
        for e in [collect_module.demo_catalog()[0]]
    ]
    filled = await collect_module._fill_nearest_stations(events, lambda *a, **k: None)
    assert filled is not None
    assert filled[0].location.nearest_station == "京橋(大阪府)"
    assert asked == ["大阪市都島区東野田町4丁目15番82号"]

    # 建物名しか無いイベントには問い合わせない（無駄な呼び出しをしない）
    asked.clear()
    building = [
        events[0].model_copy(
            update={"location": EventLocation(type="offline", venue="グランフロント大阪")}
        )
    ]
    assert await collect_module._fill_nearest_stations(building, lambda *a, **k: None) is None
    assert asked == []
