"""Public page fetching with the §9.2 limits and §10.1 safety checks.

Redirects are followed manually. ``httpx``'s ``follow_redirects=True`` would
perform hops 2..n without re-running the URL guard, which is exactly the hole
§10.1「リダイレクト後にも接続先を再検査する」asks us to close.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urljoin

import httpx

from event_agent.url_guard import UnsafeUrl, assert_safe_url

logger = logging.getLogger(__name__)

# §9.2
CONNECT_TIMEOUT = 5.0
TOTAL_TIMEOUT = 10.0
MAX_BYTES = 1_048_576
MAX_REDIRECTS = 3

ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str = ""
    excerpt: str = ""
    query: str = ""


@dataclass(frozen=True)
class FetchedPage:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    text: str
    byte_length: int
    content_hash: str
    fetched_at: datetime
    redirect_chain: tuple[str, ...] = ()
    truncated: bool = False


@dataclass(frozen=True)
class FetchRejected:
    """A page that must not be used. ``reason`` is machine-readable."""

    requested_url: str
    reason: str
    detail: str = ""


FetchResult = FetchedPage | FetchRejected


class PageSource(Protocol):
    """Where page bytes come from. Swapped for fixtures in demo and evaluation."""

    async def load(self, url: str) -> FetchResult: ...


def _content_type_allowed(value: str) -> bool:
    base = value.split(";", 1)[0].strip().casefold()
    return base in ALLOWED_CONTENT_TYPES


class HttpPageSource:
    """Real network source."""

    async def load(self, url: str) -> FetchResult:
        timeout = httpx.Timeout(TOTAL_TIMEOUT, connect=CONNECT_TIMEOUT)
        chain: list[str] = []
        current = url
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False
            ) as client:
                for _ in range(MAX_REDIRECTS + 1):
                    # 各ホップで必ず再検査する。初回だけでは不十分。
                    await assert_safe_url(current)
                    request = client.build_request("GET", current)
                    response = await client.send(request, stream=True)
                    try:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                return FetchRejected(url, "redirect-no-location")
                            chain.append(current)
                            current = urljoin(current, location)
                            continue

                        if response.status_code >= 400:
                            return FetchRejected(
                                url, "http-status", str(response.status_code)
                            )

                        content_type = response.headers.get("content-type", "")
                        if not _content_type_allowed(content_type):
                            return FetchRejected(url, "content-type", content_type)

                        # 読みながら打ち切る。読み切ってから測ると1MB超が常駐する。
                        chunks: list[bytes] = []
                        total = 0
                        truncated = False
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > MAX_BYTES:
                                truncated = True
                                break
                            chunks.append(chunk)
                        if truncated:
                            return FetchRejected(url, "too-large", str(total))

                        body = b"".join(chunks)
                        return FetchedPage(
                            requested_url=url,
                            final_url=str(response.url),
                            status_code=response.status_code,
                            content_type=content_type,
                            text=body.decode(response.encoding or "utf-8", errors="replace"),
                            byte_length=len(body),
                            content_hash=hashlib.sha256(body).hexdigest(),
                            fetched_at=datetime.now(timezone.utc),
                            redirect_chain=tuple(chain),
                        )
                    finally:
                        await response.aclose()
                return FetchRejected(url, "too-many-redirects", str(len(chain)))
        except UnsafeUrl as exc:
            return FetchRejected(url, exc.reason, exc.detail)
        except httpx.TimeoutException:
            return FetchRejected(url, "timeout")
        except httpx.HTTPError as exc:
            return FetchRejected(url, "network", str(exc))


@dataclass
class FixturePage:
    body: str
    status: int = 200
    content_type: str = "text/html; charset=utf-8"
    redirects_to: str | None = None


@dataclass
class FixturePageSource:
    """Offline source backed by in-memory pages.

    The URL guard still runs, so SSRF and redirect cases are exercised in CI
    with no network. Only the transport is faked.
    """

    pages: dict[str, FixturePage] = field(default_factory=dict)

    async def load(self, url: str) -> FetchResult:
        chain: list[str] = []
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                await assert_safe_url(current, resolve=False)
            except UnsafeUrl as exc:
                return FetchRejected(url, exc.reason, exc.detail)

            page = self.pages.get(current)
            if page is None:
                return FetchRejected(url, "not-found", current)
            if page.redirects_to:
                chain.append(current)
                current = urljoin(current, page.redirects_to)
                continue
            if page.status >= 400:
                return FetchRejected(url, "http-status", str(page.status))
            if not _content_type_allowed(page.content_type):
                return FetchRejected(url, "content-type", page.content_type)
            body = page.body.encode("utf-8")
            if len(body) > MAX_BYTES:
                return FetchRejected(url, "too-large", str(len(body)))
            return FetchedPage(
                requested_url=url,
                final_url=current,
                status_code=page.status,
                content_type=page.content_type,
                text=page.body,
                byte_length=len(body),
                content_hash=hashlib.sha256(body).hexdigest(),
                fetched_at=datetime.now(timezone.utc),
                redirect_chain=tuple(chain),
            )
        return FetchRejected(url, "too-many-redirects", str(len(chain)))


class PageFetcher:
    """Thin wrapper that records every fetch on a trajectory.

    The source resolves on first use. Building it at import time would create a
    cycle, because the demo fixtures are defined in terms of this module's
    types.
    """

    def __init__(self, source: PageSource | None = None) -> None:
        self._source = source

    @property
    def source(self) -> PageSource:
        if self._source is None:
            self._source = _default_source()
        return self._source

    @source.setter
    def source(self, value: PageSource) -> None:
        self._source = value

    async def fetch(self, url: str, trajectory=None) -> FetchResult:
        result = await self.source.load(url)
        if trajectory is not None:
            outcome = "ok" if isinstance(result, FetchedPage) else f"rejected:{result.reason}"
            trajectory.record("fetch_public_page", url, outcome)
        if isinstance(result, FetchRejected):
            logger.info("fetch rejected url=%s reason=%s", url, result.reason)
        return result


def _default_source() -> PageSource:
    from event_agent.config import settings

    if settings.use_vertex:
        return HttpPageSource()
    from event_agent.demo_pages import demo_pages

    return FixturePageSource(demo_pages())


page_fetcher = PageFetcher()
