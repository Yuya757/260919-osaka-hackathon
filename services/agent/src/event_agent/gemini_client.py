from __future__ import annotations

import json
import logging
import re
from typing import Any

from event_agent.config import settings
from event_agent.schemas import UserPreferences

logger = logging.getLogger(__name__)


class GeminiClient:
    """Vertex AI Gemini wrapper.

    Do not mix Google Search Grounding with function calling in one request
    (see docs/Agent詳細要件定義書 §3.2). Search and structured extraction are
    separate generate_content calls.
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._model_calls = 0
        if settings.use_vertex:
            try:
                from google import genai

                self._client = genai.Client(
                    vertexai=True,
                    project=settings.gcp_project_id,
                    location=settings.gcp_region,
                )
            except Exception as exc:
                logger.warning("Gemini client unavailable: %s", exc)
                self._client = None

    @property
    def demo_mode(self) -> bool:
        return self._client is None

    async def generate_text(self, prompt: str, system: str | None = None) -> str | None:
        if not self._client or self._model_calls >= settings.max_model_calls:
            return None
        self._model_calls += 1
        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.2,
            ) if system else types.GenerateContentConfig(temperature=0.2)
            response = self._client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=config,
            )
            return (getattr(response, "text", None) or "").strip() or None
        except Exception as exc:
            logger.warning("generate_text failed: %s", exc)
            return None

    async def search_with_grounding(self, query: str) -> list[dict[str, str]]:
        """Grounding-only call (no tools mixed with other function calling)."""
        if not self._client or self._model_calls >= settings.max_model_calls:
            return []
        self._model_calls += 1
        try:
            from google.genai import types

            tool = types.Tool(google_search=types.GoogleSearch())
            response = self._client.models.generate_content(
                model=settings.gemini_model,
                contents=f"日本のイベント情報: {query}",
                config=types.GenerateContentConfig(tools=[tool], temperature=0.1),
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
        interests = interests.strip(" 、。") or current.interests_prompt
        return UserPreferences(
            interestsPrompt=interests,
            targetYear=target_year,
            onlineAllowed=online_allowed,
            locations=locations or current.locations,
        )

    system = (
        "Extract event search preferences from Japanese text. "
        "Return JSON: interestsPrompt, targetYear, onlineAllowed, locations (array)."
    )
    raw = await gemini_client.generate_text(
        json.dumps({"current": current.model_dump(by_alias=True), "message": msg}, ensure_ascii=False),
        system=system,
    )
    if raw:
        try:
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            data = json.loads(cleaned)
            return UserPreferences(
                interestsPrompt=str(data.get("interestsPrompt", current.interests_prompt)),
                targetYear=int(data.get("targetYear", target_year)),
                onlineAllowed=bool(data.get("onlineAllowed", online_allowed)),
                locations=list(data.get("locations", locations or current.locations)),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return UserPreferences(
        interestsPrompt=msg or current.interests_prompt,
        targetYear=target_year,
        onlineAllowed=online_allowed,
        locations=locations or current.locations,
    )
