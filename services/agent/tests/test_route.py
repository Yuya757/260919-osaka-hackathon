from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from event_agent.clients import ekispert as ekispert_module
from event_agent.clients.ekispert import (
    EkispertClient,
    EkispertError,
    RouteNotFound,
    Station,
    StationNotFound,
)
from event_agent.entrypoints.service import app

JST = timezone(timedelta(hours=9))

STATION_RESPONSE: dict[str, Any] = {
    "ResultSet": {
        "Point": [
            {"Station": {"code": "25853", "Name": "大阪", "Type": "train"}, "Prefecture": {"Name": "大阪府"}},
            {"Station": {"code": "29089", "Name": "梅田(地下鉄)", "Type": "train"}, "Prefecture": {"Name": "大阪府"}},
        ]
    }
}

# Single-leg course: Ekispert collapses single-item arrays into objects.
COURSE_RESPONSE: dict[str, Any] = {
    "ResultSet": {
        "Course": {
            "Price": [
                {"kind": "FareSummary", "Oneway": "170"},
                {"kind": "Fare", "Oneway": "170", "selected": "true"},
            ],
            "Route": {
                "transferCount": "0",
                "Point": [
                    {"Station": {"Name": "大阪"}},
                    {"Station": {"Name": "大阪城公園"}},
                ],
                "Line": {
                    "Name": "ＪＲ大阪環状線内回り",
                    "timeOnBoard": "9",
                    "DepartureState": {"Datetime": {"text": "2026-11-05T12:40:00+09:00"}},
                    "ArrivalState": {"Datetime": {"text": "2026-11-05T12:49:00+09:00"}},
                },
            },
        }
    }
}


class FakeClient(EkispertClient):
    def __init__(self, responses: dict[str, Any]) -> None:
        super().__init__(api_key="test-key")
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        self.calls.append((path, params))
        payload = self.responses[path]
        result = payload["ResultSet"]
        if "Error" in result:
            raise EkispertError(result["Error"]["Message"])
        return result


@pytest.mark.asyncio
async def test_find_station_prefers_exact_match() -> None:
    client = FakeClient({"/station/light": STATION_RESPONSE})
    station = await client.find_station("大阪")
    assert station == Station(code="25853", name="大阪", prefecture="大阪府")
    assert client.calls[0][1]["type"] == "train"

    # Second lookup is served from cache.
    await client.find_station("大阪")
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_find_station_rejects_unknown_or_oversized_names() -> None:
    client = FakeClient({"/station/light": {"ResultSet": {}}})
    with pytest.raises(StationNotFound):
        await client.find_station("存在しない駅")
    with pytest.raises(StationNotFound):
        await client.find_station("あ" * 41)


@pytest.mark.asyncio
async def test_search_route_parses_single_leg_course() -> None:
    client = FakeClient({"/search/course/extreme": COURSE_RESPONSE})
    origin = Station(code="25853", name="大阪")
    destination = Station(code="25858", name="大阪城公園")
    arrive_by = datetime(2026, 11, 5, 13, 0, tzinfo=JST)

    route = await client.search_route_arriving_by(origin, destination, arrive_by)

    params = client.calls[0][1]
    assert params["viaList"] == "25853:25858"
    assert params["date"] == "20261105"
    assert params["time"] == "1300"
    assert params["searchType"] == "arrival"

    assert route.total_minutes == 9
    assert route.transfer_count == 0
    assert route.fare_yen == 170
    assert len(route.legs) == 1
    assert route.legs[0].from_station == "大阪"
    assert route.legs[0].to_station == "大阪城公園"
    assert route.legs[0].line == "ＪＲ大阪環状線内回り"


@pytest.mark.asyncio
async def test_search_route_converts_utc_arrival_to_jst() -> None:
    client = FakeClient({"/search/course/extreme": COURSE_RESPONSE})
    origin = Station(code="1", name="A")
    destination = Station(code="2", name="B")
    # 2026-11-05T04:00Z == 13:00 JST
    await client.search_route_arriving_by(origin, destination, datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc))
    assert client.calls[0][1]["time"] == "1300"


@pytest.mark.asyncio
async def test_search_route_without_course_raises() -> None:
    client = FakeClient({"/search/course/extreme": {"ResultSet": {}}})
    with pytest.raises(RouteNotFound):
        await client.search_route_arriving_by(Station(code="1", name="A"), Station(code="2", name="B"), datetime.now(JST))


def test_route_endpoint_returns_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient({"/station/light": STATION_RESPONSE, "/search/course/extreme": COURSE_RESPONSE})
    monkeypatch.setattr("event_agent.entrypoints.service.ekispert_client", fake)

    response = TestClient(app).get("/api/events/startup-accel/route", params={"from": "大阪"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eventId"] == "startup-accel"
    assert body["route"]["fareYen"] == 170
    assert body["route"]["legs"][0]["toStation"] == "大阪城公園"


def test_route_endpoint_rejects_online_event(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient({})
    monkeypatch.setattr("event_agent.entrypoints.service.ekispert_client", fake)
    response = TestClient(app).get("/api/events/agent-meetup/route", params={"from": "大阪"})
    assert response.status_code == 400


def test_route_endpoint_unavailable_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "event_agent.entrypoints.service.ekispert_client",
        ekispert_module.EkispertClient(api_key=None),
    )
    response = TestClient(app).get("/api/events/gemini-hack/route", params={"from": "大阪"})
    assert response.status_code == 503


def test_route_endpoint_unknown_event() -> None:
    response = TestClient(app).get("/api/events/nope/route", params={"from": "大阪"})
    assert response.status_code == 404


def test_route_endpoint_accepts_an_explicit_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    """最寄駅が未確認のイベントでも、到着駅を渡せば検索できる。"""
    fake = FakeClient({"/station/light": STATION_RESPONSE, "/search/course/extreme": COURSE_RESPONSE})
    monkeypatch.setattr("event_agent.entrypoints.service.ekispert_client", fake)

    response = TestClient(app).get(
        "/api/events/kansai-demoday/route", params={"from": "京都", "to": "大阪"}
    )
    assert response.status_code == 200, response.text
    # 駅名検索に渡ったのは会場名ではなく、指定された駅名だけ
    names = [params.get("name") for path, params in fake.calls if path == "/station/light"]
    assert names == ["京都", "大阪"]


def test_route_endpoint_never_sends_the_venue_as_a_station(monkeypatch: pytest.MonkeyPatch) -> None:
    """会場名を駅名として渡すと「駅が見つかりません」になるだけ。先に断る。

    実データではこれが常態で、最寄駅が取れたイベントの方が少ない。
    """
    from event_agent.demo.catalog import demo_catalog

    fake = FakeClient({"/station/light": STATION_RESPONSE, "/search/course/extreme": COURSE_RESPONSE})
    monkeypatch.setattr("event_agent.entrypoints.service.ekispert_client", fake)
    without_station = demo_catalog()[0].model_copy(
        update={
            "location": demo_catalog()[0].location.model_copy(
                update={"nearest_station": None, "region": "グランフロント大阪"}
            )
        }
    )
    monkeypatch.setattr(
        "event_agent.entrypoints.service._find_event", lambda event_id: without_station
    )

    response = TestClient(app).get("/api/events/gemini-hack/route", params={"from": "京都"})
    assert response.status_code == 400
    assert "到着駅" in response.json()["detail"]
    assert fake.calls == []
