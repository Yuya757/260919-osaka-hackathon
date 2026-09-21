from datetime import datetime, timedelta, timezone

from event_agent.schemas import ApiEvent, EventDates, EventLocation, Recommendation

JST = timezone(timedelta(hours=9))

# Demo catalog used when Google Search Grounding is unavailable.
# Keep search/tool steps separate from this static source in production.


def demo_catalog() -> list[ApiEvent]:
    return [
        ApiEvent(
            eventId="gemini-hack",
            title="Gemini API ハッカソン 2026",
            organizer="Google for Developers",
            category="hackathon",
            summary="Gemini APIを使い、地域や暮らしの課題を解くプロトタイプを2日間で開発します。",
            location=EventLocation(type="offline", venue="グランフロント大阪", region="大阪", nearestStation="大阪"),
            dates=EventDates(
                applicationDeadline=datetime(2026, 9, 22, 23, 59, tzinfo=JST),
                eventStart=datetime(2026, 10, 11, 10, 0, tzinfo=JST),
                eventEnd=datetime(2026, 10, 12, 18, 0, tzinfo=JST),
            ),
            officialUrl="https://developers.google.com/",
            recommendation=Recommendation(
                score=96, reason="関西開催で生成AIハッカソンの関心に強く一致します。"
            ),
            source="公式サイトで確認済み",
        ),
        ApiEvent(
            eventId="cloud-next",
            title="Cloud Builders Kansai",
            organizer="GDG Osaka",
            category="conference",
            summary="Cloud Run、Vertex AI、データ基盤の実践事例を関西の開発者が共有する1dayイベントです。",
            location=EventLocation(type="hybrid", venue="梅田スカイビル", region="大阪", nearestStation="大阪"),
            dates=EventDates(
                applicationDeadline=datetime(2026, 10, 2, 18, 0, tzinfo=JST),
                eventStart=datetime(2026, 10, 18, 10, 0, tzinfo=JST),
                eventEnd=datetime(2026, 10, 18, 18, 0, tzinfo=JST),
            ),
            officialUrl="https://gdg.community.dev/",
            recommendation=Recommendation(
                score=91, reason="GCPと関西の両方に合致するカンファレンスです。"
            ),
            source="公式サイトで確認済み",
        ),
        ApiEvent(
            eventId="agent-meetup",
            title="AI Agent Product Meetup",
            organizer="Agentic Japan",
            category="meetup",
            summary="プロダクトにAI Agentを組み込む設計、評価、運用の失敗と学びを持ち寄るオンライン勉強会です。",
            location=EventLocation(type="online", venue="Google Meet", region="オンライン"),
            dates=EventDates(
                applicationDeadline=datetime(2026, 10, 8, 12, 0, tzinfo=JST),
                eventStart=datetime(2026, 10, 9, 19, 0, tzinfo=JST),
                eventEnd=datetime(2026, 10, 9, 21, 0, tzinfo=JST),
            ),
            officialUrl="https://example.com/agent-meetup",
            recommendation=Recommendation(
                score=88, reason="AI Agentの実践共有があり、オンライン参加が可能です。"
            ),
            source="主催者ページで確認済み",
        ),
        ApiEvent(
            eventId="startup-accel",
            title="Kansai AI Accelerator Pitch Day",
            organizer="Osaka Innovation Hub",
            category="acceleration",
            summary="生成AIスタートアップ向けのアクセラレーター選考ピッチです。",
            location=EventLocation(type="offline", venue="大阪城ホール周辺", region="大阪", nearestStation="大阪城公園"),
            dates=EventDates(
                applicationDeadline=datetime(2026, 9, 30, 23, 59, tzinfo=JST),
                eventStart=datetime(2026, 11, 5, 13, 0, tzinfo=JST),
                eventEnd=datetime(2026, 11, 5, 18, 0, tzinfo=JST),
            ),
            officialUrl="https://example.com/accelerator",
            recommendation=Recommendation(
                score=80, reason="関西のアクセラレーター選考で起業関心にも対応します。"
            ),
            source="公式サイトで確認済み",
        ),
        # 申込締切が公開されていないイベント。UIは「締切なし」ではなく
        # 「未確認」と表示し、カレンダーの締切登録を無効化しなければならない（§6.6）。
        ApiEvent(
            eventId="kansai-demoday",
            title="関西スタートアップ Demo Day 2026",
            organizer="Kansai Startup Network",
            category="pitch",
            summary="関西の起業家が事業構想を発表するデモデイ。登壇枠の募集要項は公開されていますが、締切日が明記されていません。",
            location=EventLocation(
                type="offline", venue="大阪イノベーションハブ", region="大阪", nearestStation="大阪"
            ),
            dates=EventDates(
                applicationDeadline=None,
                eventStart=datetime(2026, 11, 20, 13, 0, tzinfo=JST),
                eventEnd=datetime(2026, 11, 20, 18, 0, tzinfo=JST),
            ),
            officialUrl="https://example.com/kansai-demoday-2026",
            recommendation=Recommendation(
                score=78, reason="関西開催で、起業・登壇の機会に関する関心に一致します。"
            ),
            source="公式サイトで確認済み",
        ),
    ]
