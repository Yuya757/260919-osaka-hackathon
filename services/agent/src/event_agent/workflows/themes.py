"""テーマ単位の定期収集（ADR-008 決定1）。

収集はユーザーごとではなく「ハッカソン × 地域」のテーマごとに 1 日 1 回行い、
結果を共有プールに貯める。テーマは固定の設定で、ユーザーの関心はプールに対する
読み出し時の採点でしか使わない。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from event_agent.schemas import UserPreferences

JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class CollectionTheme:
    id: str
    interests_prompt: str
    locations: tuple[str, ...]
    online_only: bool = False
    # 抽出のラベル表を切り替える種別（ジャンル拡張計画）
    kind: str = "hackathon"
    # テーマ Run で残す kind。外れたものは検証前に除外する
    allowed_kinds: tuple[str, ...] = ("hackathon",)
    # 検索クエリに使うイベントサイト。ジャンルで告知の集まる場所が違う
    site_queries: tuple[str, ...] = (
        "site:connpass.com",
        "site:peatix.com",
        "site:doorkeeper.jp OR site:techplay.jp",
    )
    # 先頭の一般検索の語尾。ジャンルで告知の言い回しが違う
    lead_query: str = "イベント 申込"

    def preferences(self, *, now: datetime) -> UserPreferences:
        # 年は固定せず JST の現在年。12 月に翌年の告知を弾かないよう、検証側には年を渡さない
        return UserPreferences(
            interestsPrompt=self.interests_prompt,
            targetYear=now.astimezone(JST).year,
            onlineAllowed=True,
            locations=list(self.locations),
        )


# ビジコンは connpass ではなく公募情報サイトと主催者（自治体・金融機関・大学）の
# ページに集まる。事前調査（ジャンル拡張計画）で読んだ告知もそうだった。
_CONTEST_SITES = (
    "site:koubo.jp OR site:compe.japandesign.ne.jp",
    "site:go.jp OR site:ac.jp",
)

# アクセラ・共創はプラットフォームに集まる。事前調査（2026-09-22）で
# AUBA（eiicon）の公募プログラムと Creww Growth のプログラム一覧を実際に取得し、
# 詳細ページから締切が取れることを確認した。
_ACCELERATOR_SITES = (
    "site:growth.creww.me OR site:creww.me",
    "site:auba.eiicon.net",
)
_COCREATION_SITES = (
    "site:auba.eiicon.net",
    "site:growth.creww.me OR site:eiicon.net",
)

COLLECTION_THEMES: tuple[CollectionTheme, ...] = (
    CollectionTheme("hackathon-kansai", "ハッカソン", ("関西", "大阪", "京都", "神戸")),
    CollectionTheme("hackathon-kanto", "ハッカソン", ("関東", "東京")),
    CollectionTheme("hackathon-chubu", "ハッカソン", ("中部", "名古屋")),
    CollectionTheme("hackathon-online", "ハッカソン", ("オンライン",), online_only=True),
    CollectionTheme(
        "contest-kansai", "ビジネスコンテスト", ("関西", "大阪", "京都", "神戸"),
        kind="contest", allowed_kinds=("contest",), site_queries=_CONTEST_SITES,
        lead_query="応募 締切",
    ),
    CollectionTheme(
        "contest-kanto", "ビジネスコンテスト", ("関東", "東京"),
        kind="contest", allowed_kinds=("contest",), site_queries=_CONTEST_SITES,
        lead_query="応募 締切",
    ),
    CollectionTheme(
        "contest-online", "ビジネスコンテスト", ("オンライン", "全国"),
        online_only=False, kind="contest", allowed_kinds=("contest",), site_queries=_CONTEST_SITES,
        lead_query="応募 締切",
    ),
    CollectionTheme(
        "accelerator-kansai", "アクセラレータープログラム", ("関西", "大阪", "京都", "神戸"),
        kind="accelerator", allowed_kinds=("accelerator", "cocreation"),
        site_queries=_ACCELERATOR_SITES, lead_query="募集 締切",
    ),
    CollectionTheme(
        "accelerator-kanto", "アクセラレータープログラム", ("関東", "東京"),
        kind="accelerator", allowed_kinds=("accelerator", "cocreation"),
        site_queries=_ACCELERATOR_SITES, lead_query="募集 締切",
    ),
    CollectionTheme(
        "accelerator-online", "アクセラレータープログラム", ("オンライン", "全国"),
        kind="accelerator", allowed_kinds=("accelerator", "cocreation"),
        site_queries=_ACCELERATOR_SITES, lead_query="募集 締切",
    ),
    CollectionTheme(
        "cocreation-kansai", "オープンイノベーション 共創プログラム", ("関西", "大阪", "京都", "神戸"),
        kind="cocreation", allowed_kinds=("cocreation", "accelerator"),
        site_queries=_COCREATION_SITES, lead_query="パートナー募集 締切",
    ),
    CollectionTheme(
        "cocreation-kanto", "オープンイノベーション 共創プログラム", ("関東", "東京"),
        kind="cocreation", allowed_kinds=("cocreation", "accelerator"),
        site_queries=_COCREATION_SITES, lead_query="パートナー募集 締切",
    ),
    CollectionTheme(
        "cocreation-online", "オープンイノベーション 共創プログラム", ("オンライン", "全国"),
        kind="cocreation", allowed_kinds=("cocreation", "accelerator"),
        site_queries=_COCREATION_SITES, lead_query="パートナー募集 締切",
    ),
)

_BY_ID = {theme.id: theme for theme in COLLECTION_THEMES}


def theme_by_id(theme_id: str) -> CollectionTheme:
    try:
        return _BY_ID[theme_id]
    except KeyError as exc:
        raise ValueError(f"unknown theme: {theme_id}") from exc


def theme_for_task_index(index: int) -> CollectionTheme:
    """Cloud Run Job の CLOUD_RUN_TASK_INDEX → テーマ。範囲外は ValueError。"""
    if not 0 <= index < len(COLLECTION_THEMES):
        raise ValueError(f"task index {index} has no theme")
    return COLLECTION_THEMES[index]
