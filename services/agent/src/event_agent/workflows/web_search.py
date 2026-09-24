"""利用者ごとの Web 検索（ADR-014）。

Google 検索グラウンディングの答えと Search Suggestions を、質問した本人にだけ返す。
規約に合わせて、ここでは次のことをしない:

* 答え・出典・検索候補をどこにも保存しない（Firestore にも Run にも書かない）
* 出典のリンクを読みに行かない・イベントにしない・共有プールやフィードに載せない
* 出典のクリックを計測しない（画面は計測のリダイレクトを通さずにリンクする）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from event_agent.clients.gemini import gemini_client
from event_agent.config import settings
from event_agent.demo.web_search import demo_grounded_answer
from event_agent.schemas import WebSearchResponse, WebSource
from event_agent.security import prompt_guard
from event_agent.storage.store import store

JST = timezone(timedelta(hours=9))
# 1 セッション（端末）あたり 1 日に使える回数。検索代を抑える
PER_SESSION_DAILY = 10


class WebSearchRefused(Exception):
    """受け付けない。``status`` は HTTP の状態、``message`` は画面に出す文。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _question(query: str) -> str:
    # 問いかけは信頼できない入力。命令ではなく検索の話題として渡す（ADR-004）
    return (
        "次の話題について、日本で開かれるイベント（ハッカソン・ビジネスコンテストなど）を"
        "Web で調べ、日本語で短く答えてください。日付は出典に書かれているものだけを挙げてください。\n"
        f"話題: {query}"
    )


async def web_search(query: str, session_id: str, *, now: datetime | None = None) -> WebSearchResponse:
    now = now or datetime.now(timezone.utc)
    cleaned = prompt_guard.sanitize_free_text(query, fallback="", max_chars=300)
    if not cleaned or prompt_guard.should_block(prompt_guard.scan(query)):
        raise WebSearchRefused(422, "その問いかけにはお答えできません。探したいイベントの地域・テーマ・時期を教えてください。")

    day = now.astimezone(JST).date().isoformat()
    if not store.reserve_quota(f"web-search:{day}:{session_id}", cap=PER_SESSION_DAILY):
        raise WebSearchRefused(429, "今日の Web 検索の回数を使い切りました。明日またお試しください。")

    if gemini_client.demo_mode:
        raw = demo_grounded_answer(cleaned)
    else:
        if not store.reserve_grounding_calls(day, 1, cap=settings.daily_grounding_cap):
            raise WebSearchRefused(429, "本日の検索の上限に達しました。明日またお試しください。")
        gemini_client.reset_call_budget()
        raw = await gemini_client.grounded_answer(_question(cleaned))
        if raw is None:
            raise WebSearchRefused(502, "Web 検索に失敗しました。時間をおいてお試しください。")

    return WebSearchResponse(
        sessionId=session_id,
        answer=raw.get("answer") or "",
        searchEntryPointHtml=raw.get("search_entry_point_html"),
        sources=[
            WebSource(title=item.get("title") or item["uri"], uri=item["uri"])
            for item in raw.get("sources", [])
            if str(item.get("uri", "")).startswith("https://")
        ],
        generatedAt=now,
    )
