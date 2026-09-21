"""Evidence records for the demo catalog (§7.2).

Real runs populate these from Google Search Grounding. In demo mode they are
static so the Evidence UI (S-08) and the confidence calculation can be exercised
end to end without calling Vertex AI.

Only the minimum quote needed for verification is stored, never a full page.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from event_agent.schemas import Evidence, GroundingMetadata

JST = timezone(timedelta(hours=9))
_RETRIEVED = datetime(2026, 9, 21, 7, 30, tzinfo=JST)


def demo_evidence() -> dict[str, list[Evidence]]:
    """Evidence keyed by ``eventId``."""
    return {
        "gemini-hack": [
            Evidence(
                evidenceId="ev-gemini-001",
                query="Gemini ハッカソン 2026 大阪",
                sourceUrl="https://developers.google.com/events/gemini-hack-2026",
                sourceType="official",
                title="Gemini API ハッカソン 2026 | Google for Developers",
                excerpt="開催日: 2026年10月11日(土)〜10月12日(日) 会場: グランフロント大阪",
                supports=["title", "dates.eventStart", "dates.eventEnd", "location"],
                retrievedAt=_RETRIEVED,
                groundingMetadata=GroundingMetadata(chunkIndex=0, supportScore=0.96),
                contentHash="9f2c1b7ad4e8" + "0" * 52,
            ),
            Evidence(
                evidenceId="ev-gemini-002",
                query="Gemini ハッカソン 2026 申込締切",
                sourceUrl="https://connpass.com/event/288001/",
                sourceType="aggregator",
                title="Gemini API ハッカソン 2026 - connpass",
                excerpt="申込締切: 2026年9月22日 23:59",
                supports=["dates.applicationDeadline", "applicationUrl"],
                retrievedAt=_RETRIEVED,
                groundingMetadata=GroundingMetadata(chunkIndex=1, supportScore=0.88),
            ),
        ],
        "cloud-next": [
            Evidence(
                evidenceId="ev-cloud-001",
                query="GDG Osaka Cloud Builders Kansai 2026",
                sourceUrl="https://gdg.community.dev/events/details/cloud-builders-kansai-2026/",
                sourceType="official",
                title="Cloud Builders Kansai | GDG Osaka",
                excerpt="2026年10月18日(日) 10:00-18:00 梅田スカイビル / オンライン併催",
                supports=["title", "dates.eventStart", "location"],
                retrievedAt=_RETRIEVED,
                groundingMetadata=GroundingMetadata(chunkIndex=0, supportScore=0.93),
            ),
            Evidence(
                evidenceId="ev-cloud-002",
                sourceUrl="https://gdgosaka.example.jp/2026/cloud-builders",
                sourceType="organizer",
                title="Cloud Builders Kansai 参加申込",
                excerpt="申込は2026年10月2日18:00まで受け付けます。",
                supports=["dates.applicationDeadline"],
                retrievedAt=_RETRIEVED,
            ),
        ],
        "agent-meetup": [
            Evidence(
                evidenceId="ev-meetup-001",
                query="AI Agent Product Meetup オンライン 2026",
                sourceUrl="https://example.com/agent-meetup",
                sourceType="organizer",
                title="AI Agent Product Meetup",
                excerpt="2026年10月9日 19:00 開始 / オンライン (Google Meet)",
                supports=["title", "dates.eventStart", "location"],
                retrievedAt=_RETRIEVED,
                groundingMetadata=GroundingMetadata(chunkIndex=0, supportScore=0.81),
            ),
        ],
        "kansai-demoday": [
            Evidence(
                evidenceId="ev-demoday-001",
                query="関西 スタートアップ デモデイ 2026",
                sourceUrl="https://example.com/kansai-demoday-2026",
                sourceType="official",
                title="関西スタートアップ Demo Day 2026",
                excerpt="2026年11月20日(金) 13:00-18:00 大阪イノベーションハブ。登壇者を募集しています。",
                # 申込締切を裏付ける根拠が無い。よって dates.applicationDeadline は
                # null のままとし、推測値を入れない（§6.6）。
                supports=["title", "dates.eventStart", "dates.eventEnd", "location"],
                retrievedAt=_RETRIEVED,
                groundingMetadata=GroundingMetadata(chunkIndex=0, supportScore=0.87),
            ),
        ],
        "startup-accel": [
            Evidence(
                evidenceId="ev-accel-001",
                query="関西 AI アクセラレーター ピッチ 2026",
                sourceUrl="https://example.com/accelerator",
                sourceType="official",
                title="Kansai AI Accelerator Pitch Day",
                excerpt="2026年11月5日(木) 13:00 大阪城ホール周辺にて開催。",
                supports=["title", "dates.eventStart", "location"],
                retrievedAt=_RETRIEVED,
                groundingMetadata=GroundingMetadata(chunkIndex=0, supportScore=0.9),
            ),
            Evidence(
                evidenceId="ev-accel-002",
                sourceUrl="https://accel-news.example.net/kansai-2026",
                sourceType="aggregator",
                title="関西AIアクセラレーター 募集要項まとめ",
                excerpt="エントリー締切は2026年9月30日23:59。",
                supports=["dates.applicationDeadline"],
                retrievedAt=_RETRIEVED,
            ),
        ],
    }
