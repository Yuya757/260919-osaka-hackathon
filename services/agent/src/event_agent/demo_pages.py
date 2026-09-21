"""Fixture pages for demo mode.

Without Vertex there are no real search results, so the pipeline would produce
nothing and the demo would look broken. These pages let the *real* fetch →
extract → validate path run end to end offline, which is also what makes the
evaluation meaningful in CI: only the transport is faked.

Kept in sync with ``demo_catalog.py`` so both paths describe the same events.
"""

from __future__ import annotations

from event_agent.page_fetcher import FixturePage, SearchHit


def _page(
    title: str,
    organizer: str,
    held: str,
    deadline: str | None,
    venue: str,
    summary: str,
    extra: str = "",
) -> FixturePage:
    deadline_row = f"<div>申込締切: {deadline}</div>" if deadline else ""
    return FixturePage(
        body=(
            "<html><head><title>{title}</title></head><body>"
            "<h1>{title}</h1>"
            "<p>{summary}</p>"
            "<div>開催日: {held}</div>"
            "{deadline_row}"
            "<div>会場: {venue}</div>"
            "<div>主催: {organizer}</div>"
            "{extra}"
            "</body></html>"
        ).format(
            title=title,
            summary=summary,
            held=held,
            deadline_row=deadline_row,
            venue=venue,
            organizer=organizer,
            extra=extra,
        )
    )


DEMO_PAGE_SOURCES: dict[str, str] = {
    "https://developers.example.com/gemini-hack-2026": "official",
    "https://gdg-osaka.example.org/cloud-builders-2026": "official",
    "https://agentic.example.jp/meetup/12": "organizer",
    "https://ksn.example.jp/demoday2026": "official",
    "https://oih.example.jp/accelerator-2026": "official",
}


def demo_pages() -> dict[str, FixturePage]:
    return {
        "https://developers.example.com/gemini-hack-2026": _page(
            "Gemini API ハッカソン 2026",
            "Google for Developers",
            "2026年10月11日 10:00 〜 10月12日 18:00",
            "2026年9月24日 23:59",
            "グランフロント大阪",
            "Gemini APIを使い、地域や暮らしの課題を解くプロトタイプを2日間で開発します。",
        ),
        "https://gdg-osaka.example.org/cloud-builders-2026": _page(
            "Cloud Builders Kansai",
            "GDG Osaka",
            "2026年10月18日 10:00",
            "2026年10月2日 18:00",
            "梅田スカイビル（オンライン併催）",
            "Cloud Run、Vertex AI、データ基盤の実践事例を関西の開発者が共有する1dayイベントです。",
        ),
        "https://agentic.example.jp/meetup/12": _page(
            "AI Agent Product Meetup",
            "Agentic Japan",
            "2026年10月9日 19:00",
            "2026年10月8日",
            "オンライン (Google Meet)",
            "プロダクトにAI Agentを組み込む設計、評価、運用の失敗と学びを持ち寄るオンライン勉強会です。",
        ),
        # 申込締切が書かれていないページ。UIで「未確認」になることの確認用。
        "https://ksn.example.jp/demoday2026": _page(
            "関西スタートアップ Demo Day 2026",
            "Kansai Startup Network",
            "2026年11月20日 13:00",
            None,
            "大阪イノベーションハブ",
            "関西の起業家が事業構想を発表するデモデイ。登壇枠を募集しています。",
        ),
        "https://oih.example.jp/accelerator-2026": _page(
            "Kansai AI Accelerator Pitch Day",
            "Osaka Innovation Hub",
            "2026年11月5日 13:00",
            "2026年9月30日 23:59",
            "大阪城ホール周辺",
            "生成AIスタートアップ向けのアクセラレーター選考ピッチです。",
            extra="<div>早割締切: 2026年8月15日</div>",
        ),
    }


def demo_search_hits(queries: list[str]) -> list[SearchHit]:
    """Stand in for grounding results in demo mode."""
    query = queries[0] if queries else ""
    return [
        SearchHit(url=url, title=url.rsplit("/", 1)[-1], excerpt="", query=query)
        for url in demo_pages()
    ]
