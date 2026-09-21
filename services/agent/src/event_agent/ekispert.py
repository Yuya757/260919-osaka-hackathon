"""駅すぱあと API client for event route search.

Only two endpoints are used, both read-only and pinned to a fixed host:
- /station/light        : station name -> station code
- /search/course/extreme: route search with arrival-time constraint

Responses are treated as untrusted data and reduced to a small typed summary.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

import httpx
from pydantic import BaseModel, Field

from event_agent.config import get_settings

logger = logging.getLogger(__name__)

EKISPERT_BASE_URL = "https://api.ekispert.jp/v1/json"
JST = timezone(timedelta(hours=9))

_CACHE_TTL = timedelta(minutes=30)
_MAX_STATION_NAME_LENGTH = 40


class EkispertError(Exception):
    """Base error for Ekispert integration."""


class EkispertNotConfigured(EkispertError):
    """EKISPERT_API_KEY is missing."""


class StationNotFound(EkispertError):
    def __init__(self, name: str) -> None:
        super().__init__(f"駅が見つかりません: {name}")
        self.name = name


class RouteNotFound(EkispertError):
    """Upstream returned no course for the requested constraint."""


class Station(BaseModel):
    code: str
    name: str
    prefecture: str | None = None


class RouteLeg(BaseModel):
    line: str
    from_station: str = Field(alias="fromStation")
    to_station: str = Field(alias="toStation")
    departure: datetime | None = None
    arrival: datetime | None = None
    minutes: int | None = None

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class RouteSummary(BaseModel):
    from_station: Station = Field(alias="fromStation")
    to_station: Station = Field(alias="toStation")
    departure: datetime
    arrival: datetime
    total_minutes: int = Field(alias="totalMinutes")
    transfer_count: int = Field(alias="transferCount")
    fare_yen: int | None = Field(default=None, alias="fareYen")
    legs: list[RouteLeg]

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


def _as_list(value: Any) -> list[Any]:
    """Ekispert collapses single-element arrays into objects."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _parse_datetime(value: Any) -> datetime | None:
    text = value.get("text") if isinstance(value, dict) else value
    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _validate_station_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or len(cleaned) > _MAX_STATION_NAME_LENGTH:
        raise StationNotFound(name)
    return cleaned


class EkispertClient:
    def __init__(self, api_key: str | None, timeout_seconds: float = 8.0) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._lock = Lock()
        self._station_cache: dict[str, tuple[datetime, Station]] = {}
        self._route_cache: dict[tuple[str, str, str, str], tuple[datetime, RouteSummary]] = {}

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if not self._api_key:
            raise EkispertNotConfigured("EKISPERT_API_KEY が設定されていません。")
        query = {"key": self._api_key, **params}
        url = f"{EKISPERT_BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.get(url, params=query)
            except httpx.TransportError as exc:
                # The upstream occasionally drops the first connection; retry once.
                logger.info("ekispert transport error on %s (%s); retrying", path, type(exc).__name__)
                response = await client.get(url, params=query)
        response.raise_for_status()
        payload = response.json()
        result = payload.get("ResultSet") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise EkispertError("駅すぱあと API から不正な応答を受信しました。")
        error = result.get("Error")
        if isinstance(error, dict):
            message = str(error.get("Message") or error.get("code") or "unknown error")
            logger.warning("ekispert error on %s: %s", path, message)
            raise EkispertError(message)
        return result

    async def find_station(self, name: str) -> Station:
        cleaned = _validate_station_name(name)
        now = datetime.now(timezone.utc)
        with self._lock:
            cached = self._station_cache.get(cleaned)
            if cached and now - cached[0] < _CACHE_TTL:
                return cached[1]

        result = await self._get("/station/light", {"name": cleaned, "type": "train"})
        points = _as_list(result.get("Point"))
        stations: list[Station] = []
        for point in points:
            if not isinstance(point, dict):
                continue
            station = point.get("Station") or {}
            code = str(station.get("code") or "")
            station_name = str(station.get("Name") or "")
            if not code or not station_name:
                continue
            prefecture = (point.get("Prefecture") or {}).get("Name")
            stations.append(
                Station(code=code, name=station_name, prefecture=str(prefecture) if prefecture else None)
            )
        if not stations:
            raise StationNotFound(cleaned)

        # Prefer an exact name match; otherwise take the API's top candidate.
        chosen = next((s for s in stations if s.name == cleaned), stations[0])
        with self._lock:
            self._station_cache[cleaned] = (now, chosen)
        return chosen

    async def search_route_arriving_by(
        self,
        origin: Station,
        destination: Station,
        arrive_by: datetime,
    ) -> RouteSummary:
        local = arrive_by.astimezone(JST)
        date = local.strftime("%Y%m%d")
        time = local.strftime("%H%M")
        key = (origin.code, destination.code, date, time)
        now = datetime.now(timezone.utc)
        with self._lock:
            cached = self._route_cache.get(key)
            if cached and now - cached[0] < _CACHE_TTL:
                return cached[1]

        result = await self._get(
            "/search/course/extreme",
            {
                "viaList": f"{origin.code}:{destination.code}",
                "date": date,
                "time": time,
                "searchType": "arrival",
                "answerCount": "1",
            },
        )
        courses = _as_list(result.get("Course"))
        if not courses or not isinstance(courses[0], dict):
            raise RouteNotFound("経路が見つかりませんでした。")
        summary = self._parse_course(courses[0], origin, destination)
        with self._lock:
            self._route_cache[key] = (now, summary)
        return summary

    @staticmethod
    def _parse_course(course: dict[str, Any], origin: Station, destination: Station) -> RouteSummary:
        route = course.get("Route") or {}
        points = _as_list(route.get("Point"))
        point_names = [
            str((p.get("Station") or {}).get("Name") or "") for p in points if isinstance(p, dict)
        ]

        legs: list[RouteLeg] = []
        for index, line in enumerate(_as_list(route.get("Line"))):
            if not isinstance(line, dict):
                continue
            from_name = point_names[index] if index < len(point_names) else origin.name
            to_name = point_names[index + 1] if index + 1 < len(point_names) else destination.name
            minutes_raw = line.get("timeOnBoard")
            legs.append(
                RouteLeg(
                    line=str(line.get("Name") or ""),
                    fromStation=from_name,
                    toStation=to_name,
                    departure=_parse_datetime((line.get("DepartureState") or {}).get("Datetime")),
                    arrival=_parse_datetime((line.get("ArrivalState") or {}).get("Datetime")),
                    minutes=int(minutes_raw) if str(minutes_raw or "").isdigit() else None,
                )
            )

        departures = [leg.departure for leg in legs if leg.departure]
        arrivals = [leg.arrival for leg in legs if leg.arrival]
        if not departures or not arrivals:
            raise RouteNotFound("経路の時刻情報を取得できませんでした。")
        departure = departures[0]
        arrival = arrivals[-1]

        fare: int | None = None
        for price in _as_list(course.get("Price")):
            if isinstance(price, dict) and price.get("kind") == "FareSummary":
                oneway = str(price.get("Oneway") or "")
                fare = int(oneway) if oneway.isdigit() else None
                break

        transfer_raw = str(route.get("transferCount") or "0")
        return RouteSummary(
            fromStation=origin,
            toStation=destination,
            departure=departure,
            arrival=arrival,
            totalMinutes=max(int((arrival - departure).total_seconds() // 60), 0),
            transferCount=int(transfer_raw) if transfer_raw.isdigit() else 0,
            fareYen=fare,
            legs=legs,
        )


ekispert_client = EkispertClient(api_key=get_settings().ekispert_api_key)
