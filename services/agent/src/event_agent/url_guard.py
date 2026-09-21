"""URL safety checks for outbound fetches (Agent詳細要件定義書 §10.1).

The agent follows URLs that come from search results and, indirectly, from
page content. Any of those can point at internal infrastructure, so every URL
is checked here before a request is made — and again after each redirect hop,
because a redirect can move a safe URL onto a private address.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})

# 解決結果に関わらず拒否するホスト名。DNSが内部を指すよう仕込まれていても止める。
DENIED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)
DENIED_SUFFIXES = ("localhost", ".localhost", ".internal", ".local")


class UnsafeUrl(Exception):
    """Raised when a URL must not be requested. ``reason`` is machine-readable."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class SafeTarget:
    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]


def _reject_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return a rejection reason for non-public addresses, else None."""
    # ::ffff:10.0.0.1 のようなIPv4射影アドレスは、包んだままだと
    # is_private が False になる実装があるので必ず展開してから判定する。
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_unspecified:
        # 0.0.0.0 / :: は is_private でもあるので、先に見て具体的な理由を返す
        return "unspecified"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        # 169.254.169.254（クラウドのメタデータサーバ）はここで落ちる
        return "link-local"
    if ip.is_private:
        return "private"
    if ip.is_reserved:
        return "reserved"
    if ip.is_multicast:
        return "multicast"
    return None


def classify_address(value: str) -> str | None:
    """Rejection reason for a literal address, or None when it is public."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return "not-an-ip"
    return _reject_ip(ip)


def check_hostname(host: str) -> None:
    host = host.strip().rstrip(".").casefold()
    if not host:
        raise UnsafeUrl("host-missing")
    if host in DENIED_HOSTNAMES or host.endswith(DENIED_SUFFIXES):
        raise UnsafeUrl("host-denied", host)


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


async def assert_safe_url(url: str, *, resolve: bool = True) -> SafeTarget:
    """Validate a URL, resolving DNS and checking every returned address.

    ``resolve=False`` skips DNS only — scheme, port and hostname checks still
    run. Fixture-backed sources use it so the offline path exercises the same
    guard as production.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.casefold()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrl("scheme", scheme or "(none)")

    host = (parts.hostname or "").strip().rstrip(".")
    check_hostname(host)

    # IPリテラルの分類をポート検査より先に行う。どちらでも拒否はするが、
    # 127.0.0.1:8080 の理由は "port" より "loopback" のほうが原因を示す。
    literal = classify_address(host)
    if literal != "not-an-ip" and literal is not None:
        raise UnsafeUrl(literal, host)

    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:  # 範囲外のポート番号
        raise UnsafeUrl("port-invalid", str(exc)) from exc
    if port not in ALLOWED_PORTS:
        raise UnsafeUrl("port", str(port))

    if literal != "not-an-ip":
        return SafeTarget(url=url, scheme=scheme, host=host, port=port, addresses=(host,))

    if not resolve:
        return SafeTarget(url=url, scheme=scheme, host=host, port=port, addresses=())

    try:
        addresses = await asyncio.to_thread(_resolve, host, port)
    except socket.gaierror as exc:
        raise UnsafeUrl("dns", str(exc)) from exc
    if not addresses:
        raise UnsafeUrl("dns", "no addresses")

    # 1つでも内部アドレスを含むなら拒否する。DNS rebinding では複数返る。
    for address in addresses:
        reason = classify_address(address)
        if reason is not None and reason != "not-an-ip":
            raise UnsafeUrl(reason, f"{host} -> {address}")

    return SafeTarget(
        url=url, scheme=scheme, host=host, port=port, addresses=tuple(addresses)
    )
