"""Doorkeeper の公開 API クライアント（技術イベント、ADR-012）。

勉強会・LT 会・もくもく会・カンファレンスは connpass / Doorkeeper に集まっていて、
件数が多い。Web を検索して本文から読むのではなく、構造化データをそのまま貰う。
Grounding 検索を使わないので検索代はゼロで、開催日時も推測が要らない。

API は認証なしでも使えるが、こちらの都合で無制限に叩いてよいわけではない:

* 1 ページ 25 件。`page` で送る
* 認証なしは 5 分あたり 300 リクエストまで。呼び出しの間隔を空け、1 回の収集で
  叩く回数に上限を置く
* 主催グループは ``expand[]=group`` を付けたときだけ名前付きで返る
* 申込締切にあたる項目は無い。締切は推測せず null のまま持つ（§6.5）

返ってくる文字列は外部入力として扱う（§10.1）。説明の HTML はモデルに渡さない。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

BASE_URL = "https://api.doorkeeper.jp"
EVENTS_PATH = "/events"
PAGE_SIZE = 25

CONNECT_TIMEOUT = 5.0
TOTAL_TIMEOUT = 20.0
# 5 分 300 回 = 1 秒 1 回。余裕を見てそれより広く取る
MIN_INTERVAL_SECONDS = 1.2
MAX_RETRIES = 2


@dataclass(frozen=True)
class MeetupListing:
    """一覧 API の 1 件。日時は JST に直して持つ。"""

    event_id: str
    title: str
    public_url: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    venue_name: str | None = None
    address: str | None = None
    description: str | None = None
    ticket_limit: int | None = None
    participants: int | None = None
    # 主催グループの名前。expand しないと id しか返らないので、そのときは None
    group_name: str | None = None


class MeetupSource(Protocol):
    """テストとデモで差し替えるための境界。"""

    async def search(
        self, keyword: str, *, since: date, until: date, page: int = 1
    ) -> list[MeetupListing]: ...


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _parse_datetime(value: Any) -> datetime | None:
    """API の UTC 表記（``2026-10-30T10:00:00.000Z``）を JST の日時にする。読めなければ None。"""
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(JST)


def listing_from_json(row: dict[str, Any]) -> MeetupListing | None:
    """一覧 1 件を写す。応答は ``{"event": {...}}`` の形。

    id・タイトル・https の公開 URL が無いものは載せられないので捨てる。
    """
    body = row.get("event") if isinstance(row.get("event"), dict) else row
    raw_id = body.get("id")
    event_id = str(raw_id) if isinstance(raw_id, (int, str)) and str(raw_id).strip() else None
    title = _text(body.get("title"))
    url = _text(body.get("public_url"))
    if not event_id or not title or not url or not url.startswith("https://"):
        return None
    group = body.get("group")
    return MeetupListing(
        event_id=event_id,
        title=title,
        public_url=url,
        starts_at=_parse_datetime(body.get("starts_at")),
        ends_at=_parse_datetime(body.get("ends_at")),
        venue_name=_text(body.get("venue_name")),
        address=_text(body.get("address")),
        description=_text(body.get("description")),
        ticket_limit=_count(body.get("ticket_limit")),
        participants=_count(body.get("participants")),
        group_name=_text(group.get("name")) if isinstance(group, dict) else None,
    )


class DoorkeeperClient:
    """本物の API を叩くクライアント。呼び出しの間隔と回数を自分で抑える。"""

    def __init__(self, *, base_url: str = BASE_URL, max_calls: int = 60) -> None:
        self._base_url = base_url.rstrip("/")
        self._max_calls = max_calls
        self._calls = 0
        self._last_call_at: float | None = None

    @property
    def calls_used(self) -> int:
        return self._calls

    def reset(self) -> None:
        self._calls = 0

    async def _get(self, params: dict[str, Any]) -> list[Any] | None:
        if self._calls >= self._max_calls:
            logger.warning("doorkeeper call budget exhausted calls=%s", self._calls)
            return None
        await self._space_out()
        self._calls += 1
        timeout = httpx.Timeout(TOTAL_TIMEOUT, connect=CONNECT_TIMEOUT)
        url = f"{self._base_url}{EVENTS_PATH}"
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(
                        url, params=params, headers={"accept": "application/json"}
                    )
            except httpx.HTTPError as exc:
                logger.warning("doorkeeper request failed error=%s", exc)
                return None
            if response.status_code == 429:
                wait = MIN_INTERVAL_SECONDS * (attempt + 1) * 4
                logger.info("doorkeeper rate limited waiting=%.2fs", wait)
                await asyncio.sleep(wait)
                continue
            if response.status_code >= 400:
                logger.warning("doorkeeper status=%s", response.status_code)
                return None
            try:
                body = response.json()
            except ValueError:
                logger.warning("doorkeeper returned non-JSON")
                return None
            return body if isinstance(body, list) else None
        return None

    async def _space_out(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self._last_call_at is not None:
            wait = MIN_INTERVAL_SECONDS - (now - self._last_call_at)
            if wait > 0:
                await asyncio.sleep(wait)
                now = loop.time()
        self._last_call_at = now

    async def search(
        self, keyword: str, *, since: date, until: date, page: int = 1
    ) -> list[MeetupListing]:
        """キーワードで期間内に始まるイベントを開催日順に引く。"""
        rows = await self._get(
            {
                "q": keyword.strip(),
                "since": since.isoformat(),
                "until": until.isoformat(),
                "sort": "starts_at",
                "locale": "ja",
                "page": page,
                # 主催グループの名前を一緒に貰う（主催者の欄に使う）
                "expand[]": "group",
            }
        )
        if not rows:
            return []
        found: list[MeetupListing] = []
        for row in rows:
            if isinstance(row, dict):
                listing = listing_from_json(row)
                if listing is not None:
                    found.append(listing)
        return found
