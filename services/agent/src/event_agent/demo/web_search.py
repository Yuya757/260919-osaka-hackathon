"""デモ用の Web 検索の答え（ADR-014）。`AGENT_DEMO_MODE` のときはネットワークに出ない。

形は Google 検索グラウンディングの応答に合わせてある（答え・Search Suggestions の HTML・出典）。
"""

from __future__ import annotations

# 本物の renderedContent と同じく、スタイル付きの小さな HTML。画面は無改変で iframe に入れる
DEMO_ENTRY_POINT_HTML = """<style>
.container{display:flex;flex-wrap:wrap;gap:6px;font-family:sans-serif}
.chip{display:inline-block;padding:6px 12px;border:1px solid #dadce0;border-radius:16px;
color:#1a0dab;text-decoration:none;font-size:13px}
.logo{font-size:12px;color:#5f6368;margin-right:6px}
</style>
<div class="container"><span class="logo">Google</span>
<a class="chip" href="https://www.google.com/search?q=%E9%96%A2%E8%A5%BF+%E3%83%8F%E3%83%83%E3%82%AB%E3%82%BD%E3%83%B3+2026" target="_blank" rel="noopener">関西 ハッカソン 2026</a>
<a class="chip" href="https://www.google.com/search?q=%E5%A4%A7%E9%98%AA+%E3%83%8F%E3%83%83%E3%82%AB%E3%82%BD%E3%83%B3+%E5%AD%A6%E7%94%9F" target="_blank" rel="noopener">大阪 ハッカソン 学生</a>
</div>"""


def demo_grounded_answer(question: str) -> dict:
    return {
        "answer": (
            f"「{question}」について、Web 上では関西で 10〜11 月に開かれるハッカソンの告知が"
            "いくつか見つかりました（デモ用の固定の答えです）。日程と申込締切は、"
            "それぞれの公式ページでご確認ください。"
        ),
        "search_entry_point_html": DEMO_ENTRY_POINT_HTML,
        "sources": [
            {"title": "example.com", "uri": "https://example.com/hackathon-2026"},
            {"title": "example.org", "uri": "https://example.org/events/kansai"},
        ],
    }
