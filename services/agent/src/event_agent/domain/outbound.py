"""外部リンクの計測用 URL（ADR-009）。

アプリから公式サイト・申込ページへ飛ぶリンクは `/api/go/{eventId}/{kind}` を経由
させ、302 で本来の URL へ送る。そのとき UTM を付ける。主催者側は自分のアクセス解析で
「このアプリ経由」を見分けられる。`normalize_url` は utm を落とすので、重複判定や
既知ページの照合には影響しない。
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

UTM_SOURCE = "cho-event-kanri"
UTM_MEDIUM = "app"


def with_utm(url: str, event_id: str) -> str:
    """既存のクエリを保ったまま utm_* を加える。既に utm があれば上書きする。"""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.startswith("utm_")]
    query.extend(
        [("utm_source", UTM_SOURCE), ("utm_medium", UTM_MEDIUM), ("utm_campaign", event_id)]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
