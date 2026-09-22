"""jGrants（デジタル庁）の公開 API クライアント（ジャンル拡張計画 段階4）。

補助金は Web を検索して本文から読むのではなく、構造化データをそのまま貰う。
Grounding 検索を使わないので検索代はゼロで、締切（公募終了日時）も推測が要らない。

API は認証不要だが、こちらの都合で無制限に叩いてよいわけではない:

* `keyword` は必須で 2 文字以上。「全件ください」はできないので、テーマごとの
  キーワードを巡回する
* ページネーションは無く、条件に合うものが一度に返る
* レート制限がある（間隔を空けても 500 リクエストあたりで 429）。呼び出しの間隔を
  空け、1 回の収集で叩く回数に上限を置く

返ってくる文字列は外部入力として扱う（§10.1）。本文 HTML はモデルに渡さない。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

BASE_URL = "https://api.jgrants-portal.go.jp"
LIST_PATH = "/exp/v1/public/subsidies"
DETAIL_PATH = "/exp/v2/public/subsidies/id/{subsidy_id}"
PUBLIC_PAGE = "https://www.jgrants-portal.go.jp/subsidy/{subsidy_id}"

CONNECT_TIMEOUT = 5.0
TOTAL_TIMEOUT = 20.0
# 連続して叩くときの最低間隔。記事の実測（150ms でも 500 件あたりで 429）より広く取る
MIN_INTERVAL_SECONDS = 0.25
MAX_RETRIES = 2


@dataclass(frozen=True)
class SubsidyListing:
    """一覧 API の 1 件。日時は JST に直して持つ。"""

    subsidy_id: str
    title: str
    name: str | None = None
    institution: str | None = None
    max_limit: int | None = None
    target_area: str | None = None
    target_employees: str | None = None
    acceptance_start: datetime | None = None
    acceptance_end: datetime | None = None


@dataclass(frozen=True)
class SubsidyDetail:
    """詳細 API のうち、掲載に使う項目だけ。本文 HTML は持たない。"""

    subsidy_id: str
    page_url: str | None = None
    institution: str | None = None
    subsidy_rate: str | None = None
    use_purpose: str | None = None
    industry: str | None = None
    target_area: str | None = None


class SubsidySource(Protocol):
    """テストとデモで差し替えるための境界。"""

    async def search(self, keyword: str, *, accepting: bool = True) -> list[SubsidyListing]: ...

    async def detail(self, subsidy_id: str) -> SubsidyDetail | None: ...


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_datetime(value: Any) -> datetime | None:
    """API の UTC 表記（``2026-10-30T14:59:00.000Z``）を JST の日時にする。

    日時は推測しない。読めない値は None にして、締切なしとして扱う（§6.5）。
    """
    text = _text(value)
    if text is None:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(JST)


def listing_from_json(row: dict[str, Any]) -> SubsidyListing | None:
    """一覧 1 件を写す。id と title が無いものは使えないので捨てる。"""
    subsidy_id = _text(row.get("id"))
    title = _text(row.get("title"))
    if not subsidy_id or not title:
        return None
    limit = row.get("subsidy_max_limit")
    return SubsidyListing(
        subsidy_id=subsidy_id,
        title=title,
        name=_text(row.get("name")),
        institution=_text(row.get("institution_name")),
        max_limit=limit if isinstance(limit, int) and limit > 0 else None,
        target_area=_text(row.get("target_area_search")),
        target_employees=_text(row.get("target_number_of_employees")),
        acceptance_start=_parse_datetime(row.get("acceptance_start_datetime")),
        acceptance_end=_parse_datetime(row.get("acceptance_end_datetime")),
    )


def detail_from_json(subsidy_id: str, row: dict[str, Any]) -> SubsidyDetail:
    return SubsidyDetail(
        subsidy_id=subsidy_id,
        page_url=_text(row.get("front_subsidy_detail_page_url")),
        institution=_text(row.get("institution_name")),
        subsidy_rate=_text(row.get("subsidy_rate")),
        use_purpose=_text(row.get("use_purpose")),
        industry=_text(row.get("industry")),
        target_area=_text(row.get("target_area_search")),
    )


def public_page_url(detail: SubsidyDetail | None, subsidy_id: str) -> str:
    """掲載に使う URL。詳細 API が返す公開ページを優先する。"""
    if detail and detail.page_url and detail.page_url.startswith("https://"):
        return detail.page_url
    return PUBLIC_PAGE.format(subsidy_id=subsidy_id)


class JGrantsClient:
    """本物の API を叩くクライアント。呼び出しの間隔と回数を自分で抑える。"""

    def __init__(self, *, base_url: str = BASE_URL, max_calls: int = 40) -> None:
        self._base_url = base_url.rstrip("/")
        self._max_calls = max_calls
        self._calls = 0
        self._last_call_at: float | None = None

    @property
    def calls_used(self) -> int:
        return self._calls

    def reset(self) -> None:
        self._calls = 0

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if self._calls >= self._max_calls:
            logger.warning("jgrants call budget exhausted calls=%s", self._calls)
            return None
        await self._space_out()
        self._calls += 1
        timeout = httpx.Timeout(TOTAL_TIMEOUT, connect=CONNECT_TIMEOUT)
        url = f"{self._base_url}{path}"
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, params=params, headers={"accept": "application/json"})
            except httpx.HTTPError as exc:
                logger.warning("jgrants request failed url=%s error=%s", url, exc)
                return None
            if response.status_code == 429:
                # 混んでいるだけ。間を置いて数回だけ試し、駄目なら諦めて次へ
                wait = MIN_INTERVAL_SECONDS * (attempt + 1) * 4
                logger.info("jgrants rate limited url=%s waiting=%.2fs", url, wait)
                await asyncio.sleep(wait)
                continue
            if response.status_code >= 400:
                logger.warning("jgrants status=%s url=%s", response.status_code, url)
                return None
            try:
                body = response.json()
            except ValueError:
                logger.warning("jgrants returned non-JSON url=%s", url)
                return None
            return body if isinstance(body, dict) else None
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

    async def search(self, keyword: str, *, accepting: bool = True) -> list[SubsidyListing]:
        """キーワードで公募中の補助金を引く。`keyword` は 2 文字以上（API の制約）。"""
        if len(keyword.strip()) < 2:
            raise ValueError("jGrants の keyword は 2 文字以上")
        body = await self._get(
            LIST_PATH,
            {
                "keyword": keyword.strip(),
                "sort": "acceptance_end_datetime",
                "order": "ASC",
                # 0 は募集終了を含む。既定は公募中だけを見る
                "acceptance": "1" if accepting else "0",
            },
        )
        if not body:
            return []
        rows = body.get("result")
        if not isinstance(rows, list):
            return []
        found: list[SubsidyListing] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            listing = listing_from_json(row)
            if listing is not None:
                found.append(listing)
        return found

    async def detail(self, subsidy_id: str) -> SubsidyDetail | None:
        body = await self._get(DETAIL_PATH.format(subsidy_id=subsidy_id))
        if not body:
            return None
        rows = body.get("result")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return detail_from_json(subsidy_id, rows[0])
        if isinstance(rows, dict):
            return detail_from_json(subsidy_id, rows)
        return None
