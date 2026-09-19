from event_agent.entrypoints.service import app


def test_health():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_chat_starts_run():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "関西の生成AIハッカソンを探して"})
    assert response.status_code == 200
    body = response.json()
    assert "reply" in body
    assert body["sessionId"]
    assert any(action["type"] == "agent_run_started" for action in body.get("actions", []))
