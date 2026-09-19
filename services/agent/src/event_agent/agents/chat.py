from __future__ import annotations

import re

from event_agent.gemini_client import extract_preferences_from_message, gemini_client
from event_agent.schemas import (
    AgentRunStartedAction,
    ChatRequest,
    ChatResponse,
    PreferencesUpdatedAction,
    UserPreferences,
    preferences_to_api_dict,
)
from event_agent.store import store
from event_agent.workflows.collect import schedule_collect_run


def _wants_search(message: str) -> bool:
    return bool(
        re.search(
            r"(探して|検索|更新|集めて|イベントを|見つけて|リストアップ)",
            message,
        )
    )


def _demo_reply(preferences: UserPreferences, started_run: bool) -> str:
    if started_run:
        return (
            f"「{preferences.interests_prompt}」で{preferences.target_year}年の"
            "イベント探索を開始しました。申込締切と開催日を分けて一覧に反映します。"
        )
    return (
        f"関心条件を「{preferences.interests_prompt}」に更新しました。"
        "「イベントを探して」と送ると探索を開始します。"
    )


async def handle_chat(request: ChatRequest) -> ChatResponse:
    session = store.get_or_create_session(request.session_id)
    previous = session.preferences.model_copy(deep=True)
    preferences = await extract_preferences_from_message(request.message, session.preferences)
    preferences_changed = preferences.model_dump() != previous.model_dump()
    session.preferences = preferences
    session.messages.append({"role": "user", "content": request.message})

    actions: list = []
    started_run = False

    if preferences_changed:
        actions.append(
            PreferencesUpdatedAction(
                type="preferences_updated",
                preferences=preferences_to_api_dict(preferences),
            )
        )

    if _wants_search(request.message):
        run = schedule_collect_run(preferences)
        actions.append(AgentRunStartedAction(type="agent_run_started", runId=run.run_id))
        started_run = True

    system = (
        "あなたはイベント探索エージェントです。日本語で短く返答し、"
        "申込締切と開催日を混同しないよう案内してください。"
    )
    prompt = (
        f"ユーザー発話: {request.message}\n"
        f"現在の関心: {preferences.model_dump(by_alias=True)}\n"
        f"探索開始済み: {started_run}\n"
        "40〜80文字で返答してください。"
    )
    generated = await gemini_client.generate_text(prompt, system=system)
    reply = generated or _demo_reply(preferences, started_run)

    session.messages.append({"role": "assistant", "content": reply})
    store.save_session(session)

    return ChatResponse(sessionId=session.session_id, reply=reply, actions=actions)
