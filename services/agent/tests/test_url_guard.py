"""SSRF guard tests (§10.1, §13.3「SSRF拒否」)."""

from __future__ import annotations

import pytest

from event_agent.security.url_guard import UnsafeUrl, assert_safe_url, classify_address


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("file:///etc/passwd", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("ftp://example.com/x", "scheme"),
        ("data:text/html,<b>x</b>", "scheme"),
        ("http://localhost/x", "host-denied"),
        ("http://LOCALHOST/x", "host-denied"),
        ("https://metadata.google.internal/computeMetadata/v1/", "host-denied"),
        ("http://foo.internal/x", "host-denied"),
        ("http://169.254.169.254/latest/meta-data/", "link-local"),
        ("http://127.0.0.1/", "loopback"),
        ("http://127.0.0.1:8080/", "loopback"),
        ("http://10.0.0.5/", "private"),
        ("http://192.168.1.1/", "private"),
        ("http://172.16.0.1/", "private"),
        ("http://[::1]/", "loopback"),
        ("http://[::ffff:10.0.0.1]/", "private"),
        ("http://0.0.0.0/", "unspecified"),
        ("https://example.com:8443/", "port"),
    ],
)
@pytest.mark.asyncio
async def test_rejects(url: str, reason: str) -> None:
    with pytest.raises(UnsafeUrl) as excinfo:
        await assert_safe_url(url, resolve=False)
    assert excinfo.value.reason == reason


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/events/1",
        "http://example.com:80/x",
        "https://sub.example.co.jp:443/a?b=1",
    ],
)
@pytest.mark.asyncio
async def test_allows_public(url: str) -> None:
    target = await assert_safe_url(url, resolve=False)
    assert target.scheme in {"http", "https"}


@pytest.mark.asyncio
async def test_dns_result_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """公開ホスト名が内部アドレスに解決されるケースを拒否する。"""
    monkeypatch.setattr("event_agent.security.url_guard._resolve", lambda host, port: ["10.1.2.3"])
    with pytest.raises(UnsafeUrl) as excinfo:
        await assert_safe_url("https://rebind.example.com/x", resolve=True)
    assert excinfo.value.reason == "private"


@pytest.mark.asyncio
async def test_one_bad_address_rejects_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """複数レコードのうち1つでも内部なら拒否する（DNS rebinding対策）。"""
    monkeypatch.setattr(
        "event_agent.security.url_guard._resolve", lambda host, port: ["93.184.216.34", "127.0.0.1"]
    )
    with pytest.raises(UnsafeUrl) as excinfo:
        await assert_safe_url("https://mixed.example.com/x", resolve=True)
    assert excinfo.value.reason == "loopback"


def test_classify_address() -> None:
    assert classify_address("8.8.8.8") is None
    assert classify_address("127.0.0.1") == "loopback"
    assert classify_address("169.254.169.254") == "link-local"
    assert classify_address("not-a-host") == "not-an-ip"


@pytest.mark.asyncio
async def test_fixture_source_enforces_the_guard() -> None:
    """オフライン経路でもURL検査を通す。

    ここを素通りさせると、評価がSSRF防御の有無を区別できなくなる。
    """
    from event_agent.clients.page_fetcher import FetchRejected, FixturePage, FixturePageSource

    bad = "http://169.254.169.254/latest/meta-data/"
    source = FixturePageSource({bad: FixturePage(body="<html><body>secret</body></html>")})
    result = await source.load(bad)
    assert isinstance(result, FetchRejected)
    assert result.reason == "link-local"
