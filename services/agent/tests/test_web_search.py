"""利用者ごとの Web 検索（ADR-014）。

規約: Google 検索グラウンディングの答えと Search Suggestions は質問した本人にだけ見せ、
保存せず、出典のリンクを読みに行かない。ここでは「保存しない」「読みに行かない」
「回数を抑える」「怪しい問いかけを拒む」を確かめる。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from event_agent.entrypoints.service import app
from test_contracts import _assert_valid, _validator
from test_chat_defense import ATTACK


def test_answers_with_suggestions_and_sources_without_saving(store_backend, monkeypatch):
    from event_agent.clients import page_fetcher as fetcher_module

    fetched: list[str] = []
    original = fetcher_module.page_fetcher.fetch

    async def spy(url, trajectory=None):
        fetched.append(url)
        return await original(url, trajectory)

    monkeypatch.setattr(fetcher_module.page_fetcher, "fetch", spy)
    events_before = store_backend.list_events()
    posts_before = store_backend.list_organizer_posts()

    with TestClient(app) as client:
        response = client.post("/api/web-search", json={"query": "関西 ハッカソン 10月"})
    assert response.status_code == 200
    body = response.json()
    _assert_valid(_validator("web-search.json", "WebSearchResponse"), body, "WebSearchResponse")
    assert body["answer"] and body["searchEntryPointHtml"] and body["sources"]

    # 出典のリンクは読みに行かない。イベントにもフィードにも載せない
    assert fetched == []
    assert store_backend.list_events() == events_before
    assert store_backend.list_organizer_posts() == posts_before


def test_refuses_injection_and_limits_calls_per_session(store_backend):
    with TestClient(app) as client:
        refused = client.post("/api/web-search", json={"query": ATTACK})
        assert refused.status_code == 422

        session = client.post("/api/web-search", json={"query": "大阪 ハッカソン"}).json()["sessionId"]
        codes = [
            client.post("/api/web-search", json={"query": "大阪 ハッカソン", "sessionId": session}).status_code
            for _ in range(12)
        ]
    assert codes.count(200) == 9 and codes[-1] == 429
