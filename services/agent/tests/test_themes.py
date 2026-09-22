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
    ]
    assert theme_for_task_index(3).id == "hackathon-online"
    with pytest.raises(ValueError):
        theme_for_task_index(4)
    assert theme_by_id("hackathon-kanto").locations == ("関東", "東京")
    assert select_themes(["job"], {"CLOUD_RUN_TASK_INDEX": "2"})[0].id == "hackathon-chubu"
    assert select_themes(["job", "hackathon-online"], {})[0].id == "hackathon-online"
    assert len(select_themes(["job"], {})) == 4


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
