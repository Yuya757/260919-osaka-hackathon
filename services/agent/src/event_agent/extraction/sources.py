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
    # コンペ・コンテストの情報集約サイト
    "compe.japandesign.ne.jp",
    "koubo.jp",
    "compe-navi.com",
)


# 記事・ブログの投稿基盤。イベント告知ではなく「まとめ記事」が多く、
# 記事中の日付を開催日と取り違えるので抽出対象から外す。
ARTICLE_HOSTS = (
    "zenn.dev",
    "qiita.com",
    "note.com",
    "medium.com",
    "hatenablog.com",
    "hatenablog.jp",
    "hateblo.jp",
    "wikipedia.org",
    "prtimes.jp",
    "startuplist.jp",
)


def is_article_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold()
    return any(host == h or host.endswith("." + h) for h in ARTICLE_HOSTS)


def source_type_for(url: str, known: dict[str, str] | None = None) -> str:
    known = known or {}
    if url in known:
        return known[url]
    host = (urlsplit(url).hostname or "").casefold()
    if any(host == h or host.endswith("." + h) for h in AGGREGATOR_HOSTS):
        return "aggregator"
    return "official" if host else "other"
