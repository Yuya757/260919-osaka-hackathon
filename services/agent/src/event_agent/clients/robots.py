"""robots.txt を守る（利用者が登録したページの取得、ADR-014）。

利用者が登録したページは、登録のときと毎朝の見守りで読みに行く。サイトが
自動取得を断っていれば読まない。robots.txt 自体も SSRF 対策を通した取得元
（page_fetcher のソース）で読む。

- robots.txt が無い（404 など）ときは許可とみなす（慣例どおり）
- 取得が安全でない宛先（私設アドレスなど）で断られたときは不許可
- ホストごとに 1 日だけ覚えておく
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from event_agent.clients.page_fetcher import FetchedPage, FetchRejected, page_fetcher

USER_AGENT = "EventAgentBot"
CACHE_SECONDS = 24 * 3600


_cache: dict[str, tuple[float, RobotFileParser | None]] = {}


def _robots_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


async def _parser_for(url: str) -> RobotFileParser | None | bool:
    """その URL のホストの robots.txt。無ければ None、読めない宛先なら False。"""
    robots = _robots_url(url)
    cached = _cache.get(robots)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    result = await page_fetcher.fetch(robots)
    parser: RobotFileParser | None
    if isinstance(result, FetchedPage):
        parser = RobotFileParser()
        parser.parse(result.text.splitlines())
    elif isinstance(result, FetchRejected) and (
        result.reason == "not-found"
        or (result.reason == "http-status" and result.detail.startswith("4"))
        or result.reason == "content-type"
    ):
        # 無い（4xx）・robots.txt ではない応答は「断っていない」とみなす
        parser = None
    else:
        # 宛先が安全でない・一時的に読めない。読めない間は取りに行かない
        return False
    _cache[robots] = (time.monotonic(), parser)
    return parser


async def allowed(url: str) -> bool:
    """この URL を自動で読みに行ってよいか。"""
    parser = await _parser_for(url)
    if parser is False:
        return False
    if parser is None:
        return True
    return parser.can_fetch(USER_AGENT, url)


def clear_cache() -> None:
    """テスト用。"""
    _cache.clear()
