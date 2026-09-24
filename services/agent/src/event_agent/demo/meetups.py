"""デモとテスト用の技術イベントデータ（ADR-012）。

形は Doorkeeper の公開 API（``GET /events``）の応答に合わせてある。
`AGENT_DEMO_MODE` のときはここを使い、ネットワークには出ない。
"""

from __future__ import annotations

from datetime import date

from event_agent.clients.doorkeeper import MeetupListing, listing_from_json

# 一覧 API（``expand[]=group`` 付き）の応答そのままの形（``{"event": {...}}``）。日時は UTC（JST 19:00 は 10:00Z）
DEMO_ROWS: list[dict] = [
    {
        "event": {
            "id": 910001,
            "title": "Python もくもく会 in 梅田 #42",
            "starts_at": "2026-10-07T10:00:00.000Z",
            "ends_at": "2026-10-07T12:00:00.000Z",
            "venue_name": "グランフロント大阪 ナレッジキャピタル",
            "address": "大阪府大阪市北区大深町3-1",
            "ticket_limit": 30,
            "participants": 12,
            "group": {"id": 5101, "name": "梅田Python"},
            "description": "<p>各自の作業を持ち寄るもくもく会です。初心者歓迎。</p>",
            "public_url": "https://py-umeda.doorkeeper.jp/events/910001",
        },
        "keywords": ["もくもく会", "勉強会"],
    },
    {
        "event": {
            "id": 910002,
            "title": "生成AI LT Night vol.8（オンライン）",
            "starts_at": "2026-10-15T10:30:00.000Z",
            "ends_at": "2026-10-15T12:30:00.000Z",
            "venue_name": "オンライン（YouTube Live）",
            "address": "",
            "ticket_limit": 200,
            "participants": 87,
            "group": {"id": 5102, "name": "生成AI LT実行委員会"},
            "description": "<p>生成AIの実践を5分ずつ話すLT会です。</p>",
            "public_url": "https://genai-lt.doorkeeper.jp/events/910002",
        },
        "keywords": ["LT", "勉強会"],
    },
    {
        "event": {
            "id": 910003,
            "title": "Kubernetes ハンズオン勉強会 福岡",
            "starts_at": "2026-10-24T04:00:00.000Z",
            "ends_at": "2026-10-24T08:00:00.000Z",
            "venue_name": "天神エンジニアカフェ",
            "address": "福岡県福岡市中央区天神1-15-30",
            "ticket_limit": 40,
            "participants": 21,
            "group": {"id": 5103, "name": "Kubernetes Meetup Fukuoka"},
            "description": "<p>手を動かしてクラスタを組みます。PC持参。</p>",
            "public_url": "https://k8s-fukuoka.doorkeeper.jp/events/910003",
        },
        "keywords": ["ハンズオン", "勉強会"],
    },
    {
        "event": {
            "id": 910004,
            "title": "Tokyo Frontend Conference 2026",
            "starts_at": "2026-11-14T01:00:00.000Z",
            "ends_at": "2026-11-14T09:00:00.000Z",
            "venue_name": "渋谷ストリームホール（オンライン配信あり）",
            "address": "東京都渋谷区渋谷3-21-3",
            "ticket_limit": 500,
            "participants": 312,
            "group": {"id": 5104, "name": "Tokyo Frontend Conference 実行委員会"},
            "description": "<p>フロントエンドの年次カンファレンス。</p>",
            "public_url": "https://tfc.doorkeeper.jp/events/910004",
        },
        "keywords": ["カンファレンス"],
    },
    {
        "event": {
            "id": 910005,
            "title": "札幌 Go Meetup #19",
            "starts_at": "2026-10-20T09:30:00.000Z",
            "ends_at": None,
            "venue_name": "札幌駅前ビル 会議室",
            "address": "北海道札幌市中央区北5条西2丁目",
            "ticket_limit": 25,
            "participants": 9,
            "group": {"id": 5105, "name": "Sapporo Gophers"},
            "description": "<p>Go の話をする会です。</p>",
            "public_url": "https://go-sapporo.doorkeeper.jp/events/910005",
        },
        "keywords": ["Meetup", "勉強会"],
    },
]


class DemoMeetupSource:
    """固定データを返す `MeetupSource`。キーワードは行の ``keywords`` で照合する。"""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows if rows is not None else DEMO_ROWS
        self.searched: list[tuple[str, int]] = []

    async def search(
        self, keyword: str, *, since: date, until: date, page: int = 1
    ) -> list[MeetupListing]:
        self.searched.append((keyword, page))
        if page > 1:
            return []
        found: list[MeetupListing] = []
        for row in self._rows:
            if keyword not in row.get("keywords", []):
                continue
            listing = listing_from_json(row)
            if listing is None or listing.starts_at is None:
                continue
            if not since <= listing.starts_at.date() <= until:
                continue
            found.append(listing)
        return found
