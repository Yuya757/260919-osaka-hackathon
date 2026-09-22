"""デモとテスト用の補助金データ（ジャンル拡張計画 段階4）。

形は jGrants の公開 API に合わせてある（実際の応答を見て写した）。
`AGENT_DEMO_MODE` のときはここを使い、ネットワークには出ない。
"""

from __future__ import annotations

from event_agent.clients.jgrants import (
    SubsidyDetail,
    SubsidyListing,
    detail_from_json,
    listing_from_json,
)

# 一覧 API の応答そのままの形。日時は UTC（JST 23:59 は 14:59Z）
DEMO_ROWS: list[dict] = [
    {
        "id": "demo-subsidy-0001",
        "name": "S-00012345",
        "title": "大阪府 中小企業スタートアップ支援補助金",
        "institution_name": "大阪府",
        "subsidy_max_limit": 3000000,
        "target_area_search": "大阪府",
        "target_number_of_employees": "従業員数の制約なし",
        "acceptance_start_datetime": "2026-09-01T00:00:00.000Z",
        "acceptance_end_datetime": "2026-11-27T14:59:00.000Z",
        "keywords": ["創業", "スタートアップ", "補助金"],
    },
    {
        "id": "demo-subsidy-0002",
        "name": "S-00012346",
        "title": "IT導入補助金2026（デジタル化基盤導入枠）",
        "institution_name": "経済産業省",
        "subsidy_max_limit": 4500000,
        "target_area_search": "全国",
        "target_number_of_employees": "300人以下",
        "acceptance_start_datetime": "2026-04-01T00:00:00.000Z",
        "acceptance_end_datetime": "2026-10-16T14:59:00.000Z",
        "keywords": ["DX", "IT導入", "補助金"],
    },
    {
        "id": "demo-subsidy-0003",
        "name": "S-00012347",
        "title": "ものづくり・商業・サービス生産性向上促進補助金",
        "institution_name": "中小企業庁",
        "subsidy_max_limit": 10000000,
        "target_area_search": "全国",
        "target_number_of_employees": "従業員数の制約なし",
        "acceptance_start_datetime": "2026-07-01T00:00:00.000Z",
        "acceptance_end_datetime": "2027-01-15T14:59:00.000Z",
        "keywords": ["ものづくり", "設備投資", "補助金"],
    },
    # 公募が終わっているもの。募集中だけを見るので出てこない
    {
        "id": "demo-subsidy-0004",
        "name": "S-00012348",
        "title": "令和7年度 事業再構築補助金（第12回公募）",
        "institution_name": "中小企業庁",
        "subsidy_max_limit": 20000000,
        "target_area_search": "全国",
        "target_number_of_employees": "従業員数の制約なし",
        "acceptance_start_datetime": "2025-11-01T00:00:00.000Z",
        "acceptance_end_datetime": "2026-03-26T14:59:00.000Z",
        "keywords": ["設備投資", "補助金"],
    },
]

DEMO_DETAILS: dict[str, dict] = {
    "demo-subsidy-0001": {
        "front_subsidy_detail_page_url": "https://www.jgrants-portal.go.jp/subsidy/demo-subsidy-0001",
        "institution_name": "大阪府",
        "subsidy_rate": "2/3",
        "use_purpose": "新たな事業を行いたい",
        "industry": "業種の制約なし",
        "target_area_search": "大阪府",
    },
    "demo-subsidy-0002": {
        "front_subsidy_detail_page_url": "https://www.jgrants-portal.go.jp/subsidy/demo-subsidy-0002",
        "institution_name": "経済産業省",
        "subsidy_rate": "1/2",
        "use_purpose": "IT・デジタル化を進めたい",
        "industry": "業種の制約なし",
        "target_area_search": "全国",
    },
    "demo-subsidy-0003": {
        "front_subsidy_detail_page_url": "https://www.jgrants-portal.go.jp/subsidy/demo-subsidy-0003",
        "institution_name": "中小企業庁",
        "subsidy_rate": "1/2（小規模事業者は2/3）",
        "use_purpose": "設備整備・導入したい",
        "industry": "製造業",
        "target_area_search": "全国",
    },
}


class DemoSubsidySource:
    """固定データを返す `SubsidySource`。キーワードは行の ``keywords`` で照合する。"""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows if rows is not None else DEMO_ROWS
        self.searched: list[str] = []
        self.detailed: list[str] = []

    async def search(self, keyword: str, *, accepting: bool = True) -> list[SubsidyListing]:
        self.searched.append(keyword)
        found: list[SubsidyListing] = []
        for row in self._rows:
            if keyword not in row.get("keywords", []):
                continue
            listing = listing_from_json(row)
            if listing is not None:
                found.append(listing)
        return found

    async def detail(self, subsidy_id: str) -> SubsidyDetail | None:
        self.detailed.append(subsidy_id)
        row = DEMO_DETAILS.get(subsidy_id)
        return detail_from_json(subsidy_id, row) if row else None
