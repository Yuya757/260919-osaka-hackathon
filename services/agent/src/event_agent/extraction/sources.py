"""ページの出典種別（§7.2 sourceType）を URL から決める。

デモ用の固定表に無い実ページは、集約サイトの既知ホストなら ``aggregator``、
それ以外は主催者が管理するサイトとみなして ``official`` にする。§8-2 の
「集約サイト単独の下限 0.60」はこの分類の上で効く。
"""

from __future__ import annotations

from urllib.parse import urlsplit

AGGREGATOR_HOSTS = (
    "connpass.com",
    "doorkeeper.jp",
    "peatix.com",
    "techplay.jp",
    "eventbrite.com",
    "eventbrite.jp",
    "meetup.com",
    "kokuchpro.com",
    "eventregist.com",
    "compass.jp",
)


def source_type_for(url: str, known: dict[str, str] | None = None) -> str:
    known = known or {}
    if url in known:
        return known[url]
    host = (urlsplit(url).hostname or "").casefold()
    if any(host == h or host.endswith("." + h) for h in AGGREGATOR_HOSTS):
        return "aggregator"
    return "official" if host else "other"
