"""駅すぱあと API client for event route search.

Only three endpoints are used, all read-only and pinned to a fixed host:
- /station/light        : station name -> station code
- /address/station      : venue address -> nearest stations (no geocoding needed)
- /search/course/extreme: route search with arrival-time constraint

Responses are treated as untrusted data and reduced to a small typed summary.
"""

from __future__ import annotations

import logging
import re
import unicodedata
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


_POSTAL = re.compile(r"〒?\s*\d{3}-\d{4}")
_BANCHI = re.compile(r"(\d+)\s*(?:丁目|番地|番|号)")


def normalize_address(address: str) -> str:
    """住所検索に渡す形に整える。

    ドキュメントの例は「東京都杉並区高円寺北2,500」で、丁目・番・号の漢字は
    入っていない。実際、漢字混じりのまま渡すと 400 が返る。
    郵便番号と、番地より後ろのビル名・階数も落とす。
    """
    text = unicodedata.normalize("NFKC", address)
    text = _POSTAL.sub("", text).strip()
    text = _BANCHI.sub(r"\1-", text)
    text = re.sub(r"-{2,}", "-", text)
    # 「…1-1-3 グランフロント大阪 3F」→「…1-1-3」。番地の後ろはビル名で住所ではない
    kept: list[str] = []
    seen_number = False
    for token in text.split():
        has_number = any(char.isdigit() for char in token)
        if seen_number and not has_number:
            break
        kept.append(token)
        seen_number = seen_number or has_number
    return " ".join(kept).strip(" 　-")


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
                # 例外そのものは出さない（文面に URL とキーが入る）
                logger.info("ekispert transport error on %s (%s); retrying", path, type(exc).__name__)
                response = await client.get(url, params=query)
        if response.status_code >= 400:
            # httpx の例外文にはクエリ文字列つきの URL が入る。そこにアクセスキーが
            # 載っているので、例外もレスポンス本文もログへ出さない（§10.1）
            raise EkispertError(f"駅すぱあと API がエラーを返しました（HTTP {response.status_code}）")
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

    async def find_station_near_address(
        self, address: str, *, radius_m: int = 3000
    ) -> Station | None:
        """住所テキストから最寄駅を引く（`/address/station`）。

        駅すぱあとが住所を解釈してくれるので、ジオコーディングは要らない。
        返るのは駅と直線距離（メートル）で、いちばん近いものを採る。

        これは補助であって、失敗しても経路検索そのものは続けられる（利用者に
        到着駅を入力してもらう）。プランに含まれない・住所を解釈できないなど、
        どの失敗でも None を返して呼び出し側に判断させる。
        """
        cleaned = address.strip()
        if not cleaned:
            return None
        cache_key = f"addr:{cleaned}:{radius_m}"
        now = datetime.now(timezone.utc)
        with self._lock:
            cached = self._station_cache.get(cache_key)
            if cached and now - cached[0] < _CACHE_TTL:
                return cached[1]

        # 書式で弾かれることがあるので、整えた形 → 素の形の順に 1 回ずつ試す
        attempts: list[dict[str, str]] = []
        normalized = normalize_address(cleaned)
        if normalized:
            attempts.append(
                {"address": f"{normalized},{radius_m}", "type": "train", "stationCount": "3"}
            )
        if normalized != cleaned:
            attempts.append({"address": cleaned})

        result: dict[str, Any] | None = None
        try:
            for params in attempts:
                try:
                    result = await self._get("/address/station", params)
                    break
                except EkispertError as exc:
                    logger.info(
                        "address lookup attempt failed for %r: %s", params["address"][:40], exc
                    )
            if result is None:
                return None
        except EkispertError as exc:
            # 例外文にキーを混ぜない作りにしてあるが、住所と状況だけで十分
            logger.info("address lookup failed for %r: %s", cleaned[:40], exc)
            return None
        except httpx.HTTPError as exc:
            logger.info("address lookup failed for %r: %s", cleaned[:40], type(exc).__name__)
            return None

        best: tuple[float, Station] | None = None
        for point in _as_list(result.get("Point")):
            if not isinstance(point, dict):
                continue
            station = point.get("Station") or {}
            code = str(station.get("code") or "")
            name = str(station.get("Name") or "")
            if not code or not name:
                continue
            raw_distance = point.get("Distance")
            try:
                distance = float(str(raw_distance))
            except (TypeError, ValueError):
                distance = float("inf")
            prefecture = (point.get("Prefecture") or {}).get("Name")
            candidate = Station(
                code=code, name=name, prefecture=str(prefecture) if prefecture else None
            )
            if best is None or distance < best[0]:
                best = (distance, candidate)
        if best is None:
            return None
        with self._lock:
            self._station_cache[cache_key] = (now, best[1])
        return best[1]

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
