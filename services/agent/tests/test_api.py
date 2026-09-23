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


def test_event_list_carries_evidence_preview(reset_store):
    """一覧の各行に根拠（出典と引用）が付く。全文は evidence API（§7.2）。"""
    import time

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        run_id = client.post("/api/agent-runs", json={"forceRefresh": True}).json()["runId"]
        for _ in range(200):
            body = client.get(f"/api/agent-runs/{run_id}").json()
            if body["status"] in ("succeeded", "partial_success", "failed"):
                break
            time.sleep(0.05)
        events = client.get("/api/events", params={"sourceRunId": run_id}).json()["events"]
        assert events
        for event in events:
            preview = event["evidencePreview"]
            assert preview, event["title"]
            assert all(p["excerpt"] and p["sourceUrl"] and p["supports"] for p in preview)
            assert len(preview) <= 4
        # 締切が分かるイベントは、その根拠が先頭に来る
        with_deadline = [e for e in events if e["dates"]["applicationDeadline"]]
        assert with_deadline
        assert "dates.applicationDeadline" in with_deadline[0]["evidencePreview"][0]["supports"]
