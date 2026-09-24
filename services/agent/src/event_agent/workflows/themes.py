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
    # 収集元。"search" は Grounding 検索、"jgrants" は jGrants の公開 API（段階4）、
    # "doorkeeper" は Doorkeeper の公開 API（技術イベント、ADR-012）
    source: str = "search"
    # 公開 API に渡すキーワード。source が "search" 以外のときだけ使う
    # （jGrants は API の制約で 2 文字以上）
    keywords: tuple[str, ...] = ()
    # 対象地域の絞り込み（jGrants の target_area_search と前方一致）。空なら絞らない
    target_areas: tuple[str, ...] = ()

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

# 技術イベントの告知は connpass に最も集まる。connpass の API はキーが要るので、
# キーが取れるまでは検索で connpass のページを拾う（ADR-012）。
# 1 テーマ 3 回（一般検索 + connpass 2 回）で、7 地域 21 回/日
_MEETUP_SITES = (
    "site:connpass.com",
    "site:connpass.com LT会 OR もくもく会",
)


def _meetup_search_theme(theme_id: str, locations: tuple[str, ...], *, online_only: bool = False) -> CollectionTheme:
    return CollectionTheme(
        theme_id, "技術勉強会", locations, online_only=online_only,
        kind="meetup", allowed_kinds=("meetup",), site_queries=_MEETUP_SITES,
        lead_query="勉強会 参加申込",
    )


# 毎朝の定期収集。Google 検索グラウンディングは使わない（ADR-014）。
# 収集元は公開 API（Doorkeeper）と、利用者が登録したページの見守りだけ
COLLECTION_THEMES: tuple[CollectionTheme, ...] = (
    # 技術イベント（勉強会・LT 会・もくもく会・ハンズオン・カンファレンス）は
    # Doorkeeper の公開 API から貰う（ADR-012）。検索代ゼロで件数が多い。
    # 地域は全国まとめて取り、住所の都道府県で読み出し時に絞る
    CollectionTheme(
        "meetup-study", "技術勉強会", ("全国",),
        kind="meetup", allowed_kinds=("meetup",),
        source="doorkeeper", keywords=("勉強会", "もくもく会", "ハンズオン"),
    ),
    CollectionTheme(
        "meetup-talk", "LT会・カンファレンス", ("全国",),
        kind="meetup", allowed_kinds=("meetup",),
        source="doorkeeper", keywords=("LT", "Meetup", "カンファレンス"),
    ),
)

# Google 検索グラウンディングで告知ページを見つけるテーマ。規約上、結果のリンクから
# 読むページを決めて保存・共有することはできないので、本番では使わない（ADR-014）。
# デモと評価のフィクスチャのページで、抽出と検証の経路を確かめるためだけに残す
GROUNDING_THEMES: tuple[CollectionTheme, ...] = (
    CollectionTheme("hackathon-kansai", "ハッカソン", ("関西", "大阪", "京都", "神戸")),
    CollectionTheme("hackathon-kanto", "ハッカソン", ("関東", "東京")),
    CollectionTheme("hackathon-chubu", "ハッカソン", ("中部", "名古屋")),
    CollectionTheme("hackathon-online", "ハッカソン", ("オンライン",), online_only=True),
    # 興味登録で全国の地方区分を選べるようにしたので、関西・関東・中部以外も集める
    CollectionTheme("hackathon-hokkaido-tohoku", "ハッカソン", ("北海道", "東北", "札幌", "仙台")),
    CollectionTheme("hackathon-chugoku-shikoku", "ハッカソン", ("中国地方", "四国", "広島", "岡山")),
    CollectionTheme("hackathon-kyushu-okinawa", "ハッカソン", ("九州", "沖縄", "福岡")),
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
    # connpass の技術イベントは検索で拾う。地域ごとに分けて、検索結果に出る件数を稼ぐ
    _meetup_search_theme("meetup-connpass-kansai", ("関西", "大阪", "京都", "神戸")),
    _meetup_search_theme("meetup-connpass-kanto", ("関東", "東京")),
    _meetup_search_theme("meetup-connpass-chubu", ("中部", "名古屋")),
    _meetup_search_theme("meetup-connpass-hokkaido-tohoku", ("北海道", "東北", "札幌", "仙台")),
    _meetup_search_theme("meetup-connpass-chugoku-shikoku", ("中国地方", "四国", "広島", "岡山")),
    _meetup_search_theme("meetup-connpass-kyushu-okinawa", ("九州", "沖縄", "福岡")),
    _meetup_search_theme("meetup-connpass-online", ("オンライン",), online_only=True),
)

# 一旦止めているテーマ。補助金は一覧のノイズになったため止めた。
# アクセラ・共創は検索グラウンディングを使うので、本番では使えない（ADR-014）。
# theme_by_id では引けるので、テストはそのまま使える
PAUSED_THEMES: tuple[CollectionTheme, ...] = (
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
    # 補助金は Web を検索せず jGrants の公開 API から貰う（ADR-011）。検索代ゼロ。
    # キーワードは API の制約で 2 文字以上。「全件ください」はできないので巡回する
    CollectionTheme(
        "subsidy-startup", "創業・スタートアップの補助金", ("全国",),
        kind="subsidy", allowed_kinds=("subsidy",),
        source="jgrants", keywords=("創業", "スタートアップ"),
    ),
    CollectionTheme(
        "subsidy-dx", "DX・IT導入の補助金", ("全国",),
        kind="subsidy", allowed_kinds=("subsidy",),
        source="jgrants", keywords=("DX", "IT導入"),
    ),
    CollectionTheme(
        "subsidy-monozukuri", "ものづくり・設備投資の補助金", ("全国",),
        kind="subsidy", allowed_kinds=("subsidy",),
        source="jgrants", keywords=("ものづくり", "設備投資"),
    ),
    CollectionTheme(
        "subsidy-kansai", "関西の補助金", ("関西", "大阪"),
        kind="subsidy", allowed_kinds=("subsidy",),
        source="jgrants", keywords=("補助金", "助成金"),
        target_areas=("大阪", "京都", "兵庫", "奈良", "滋賀", "和歌山", "全国"),
    ),
)

_BY_ID = {theme.id: theme for theme in COLLECTION_THEMES + GROUNDING_THEMES + PAUSED_THEMES}


def search_themes() -> tuple[CollectionTheme, ...]:
    """毎朝の定期収集のうち Grounding 検索を使うテーマ。ADR-014 以降は空であるべき。"""
    return tuple(theme for theme in COLLECTION_THEMES if theme.source == "search")


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
