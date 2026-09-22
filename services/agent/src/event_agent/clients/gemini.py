from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from event_agent.config import settings
from event_agent.schemas import UserPreferences
from event_agent.security import prompt_guard

logger = logging.getLogger(__name__)
# 3.x 系は thought_signature パーツを返し、genai が text 連結のたびに警告を出す。
# 本文だけ使うので抑える。
logging.getLogger("google_genai.types").setLevel(logging.ERROR)


@dataclass
class _CallBudget:
    """§9.2「Gemini呼び出し: 1 Run最大15回」の残数。"""

    limit: int
    used: int = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


# Run単位の予算。ContextVar にするのは、`asyncio.create_task` がコンテキストを
# コピーするため、同時に走るRunが別々の残数を持てるから。インスタンス変数だと
# 後から始まったRunの reset が先行Runの残数を消し、上限が1 Runあたりでは
# なくなる。
_call_budget: ContextVar[_CallBudget | None] = ContextVar(
    "gemini_call_budget", default=None
)


class GeminiClient:
    """Vertex AI Gemini wrapper.

    Do not mix Google Search Grounding with function calling in one request
    (see docs/Agent詳細要件定義書 §3.2). Search and structured extraction are
    separate generate_content calls.
    """

    def __init__(self) -> None:
        self._client: Any = None
        if settings.use_vertex:
            try:
                from google import genai

                self._client = genai.Client(
                    vertexai=True,
                    project=settings.gcp_project_id,
                    location=settings.gemini_location,
                )
            except Exception as exc:
                logger.warning("Gemini client unavailable: %s", exc)
                self._client = None

    @property
    def demo_mode(self) -> bool:
        return self._client is None

    def reset_call_budget(self) -> None:
        """Start a fresh per-run model-call budget (§9.2「1 Run最大15回」).

        Called at the top of every run. The budget lives in a ContextVar, so a
        run started while another is in flight gets its own allowance instead
        of resetting the one already running.
        """
        _call_budget.set(_CallBudget(settings.max_model_calls))

    @property
    def calls_used(self) -> int:
        """Calls spent by the run in the current context."""
        budget = _call_budget.get()
        return budget.used if budget else 0

    def _take_call(self) -> bool:
        budget = _call_budget.get()
        if budget is None:
            # 単体呼び出しなど、Runの外から使われた場合。
            budget = _CallBudget(settings.max_model_calls)
            _call_budget.set(budget)
        return budget.take()

    async def generate_text(
        self, prompt: str, system: str | None = None, *, thinking: bool = False
    ) -> str | None:
        """One text call. ``thinking=False`` turns reasoning off (thinking_budget=0):
        the extraction asks the model to *quote* lines, which needs no deliberation
        and with reasoning on takes minutes per page on the 3.x models."""
        if not self._client or not self._take_call():
            return None
        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.2,
                thinking_config=None if thinking else types.ThinkingConfig(thinking_budget=0),
            )
            # 同期版は event loop を塞ぐ。並列に呼ぶために aio を使い、上限時間も切る
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=prompt,
                    config=config,
                ),
                timeout=settings.model_call_timeout_seconds,
            )
            return (getattr(response, "text", None) or "").strip() or None
        except Exception as exc:
            logger.warning("generate_text failed: %s", exc)
            return None

    async def search_with_grounding(
        self,
        query: str,
        *,
        since: datetime | None = None,
        exclude_domains: tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        """Grounding-only call (no tools mixed with other function calling).

        ``since`` narrows the search to pages from that time on (Google Search
        の期間指定), and ``exclude_domains`` drops hosts that are never event
        pages (まとめ記事など). Both are search-side filters, so they cost no
        extra model calls.
        """
        if not self._client or not self._take_call():
            return []
        try:
            from google.genai import types

            search = types.GoogleSearch(
                time_range_filter=types.Interval(start_time=since, end_time=datetime.now(timezone.utc))
                if since
                else None,
                exclude_domains=list(exclude_domains) or None,
            )
            tool = types.Tool(google_search=search)
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=f"日本のイベント情報: {query}",
                    config=types.GenerateContentConfig(
                        tools=[tool],
                        temperature=0.1,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                ),
                timeout=settings.model_call_timeout_seconds,
            )
            hits: list[dict[str, str]] = []
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                gm = getattr(candidates[0], "grounding_metadata", None)
                if gm:
                    for chunk in getattr(gm, "grounding_chunks", None) or []:
                        web = getattr(chunk, "web", None)
                        if web and getattr(web, "uri", None):
                            hits.append(
                                {
                                    "url": web.uri,
                                    "title": getattr(web, "title", "") or query,
                                    "excerpt": (response.text or "")[:400],
                                }
                            )
            return hits[:10]
        except Exception as exc:
            logger.warning("grounding search failed: %s", exc)
            return []


gemini_client = GeminiClient()


async def extract_preferences_from_message(
    message: str, current: UserPreferences
) -> UserPreferences:
    msg = message.strip()
    if not msg:
        return current

    year_match = re.search(r"(20\d{2})", msg)
    target_year = int(year_match.group(1)) if year_match else current.target_year
    locations = list(current.locations)
    for place in ("関西", "大阪", "京都", "神戸", "東京", "オンライン"):
        if place in msg and place not in locations:
            locations.append(place)
    online_allowed = current.online_allowed
    if "オンライン" in msg and "不可" not in msg:
        online_allowed = True
    if "会場のみ" in msg or "オフラインのみ" in msg:
        online_allowed = False

    if gemini_client.demo_mode:
        interests = msg
        for noise in ("探して", "更新して", "ください", "お願い", "見つけて"):
            interests = interests.replace(noise, "")
        interests = prompt_guard.sanitize_free_text(
            interests.strip(" 、。"), fallback=current.interests_prompt
        )
        return UserPreferences(
            interestsPrompt=interests,
            targetYear=target_year,
            onlineAllowed=online_allowed,
            locations=locations or current.locations,
        )

    system = prompt_guard.defended_system_prompt(
        "Extract event search preferences from the delimited Japanese text. "
        "Return JSON only: interestsPrompt, targetYear, onlineAllowed, locations (array)."
    )
    message_block, _ = prompt_guard.wrap_untrusted(
        msg, label="UNTRUSTED_USER_MESSAGE", source="chat"
    )
    raw = await gemini_client.generate_text(
        json.dumps({"current": current.model_dump(by_alias=True)}, ensure_ascii=False)
        + "\n"
        + message_block,
        system=system,
    )
    if prompt_guard.leaked_canary(raw):
        logger.warning("CANARY_LEAKED in preference extraction")
        raw = None
    if raw:
        try:
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            data = json.loads(cleaned)
            return UserPreferences(
                # モデルの出力もそのままは信用しない（§7.5と同じ姿勢）
                interestsPrompt=prompt_guard.sanitize_free_text(
                    str(data.get("interestsPrompt", "")),
                    fallback=current.interests_prompt,
                ),
                targetYear=int(data.get("targetYear", target_year)),
                onlineAllowed=bool(data.get("onlineAllowed", online_allowed)),
                locations=list(data.get("locations", locations or current.locations)),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return UserPreferences(
        interestsPrompt=prompt_guard.sanitize_free_text(
            msg, fallback=current.interests_prompt
        ),
        targetYear=target_year,
        onlineAllowed=online_allowed,
        locations=locations or current.locations,
    )
