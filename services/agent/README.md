# Event Agent Service

FastAPI + ADK-style deterministic workflow for event discovery. Uses Vertex AI Gemini when `GCP_PROJECT_ID` is set; otherwise serves curated demo events for local UI development.

## API

- `GET /api/health`
- `POST /api/chat` — `{ "sessionId?", "message" }` → `{ sessionId, reply, actions? }`
- `POST /api/agent-runs` — `{ "forceRefresh?" }` → `{ runId, status }`
- `GET /api/agent-runs/{runId}`
- `GET /api/events?sourceRunId=`

## Local run (WSL)

```bash
cd services/agent
pip install -r requirements.txt
cp .env.example .env
export PYTHONPATH=src
uvicorn event_agent.entrypoints.service:app --reload --host 0.0.0.0 --port 8080
```

## Tests

```bash
export PYTHONPATH=src
pytest tests/ -q
```

## Docker

```bash
docker build -t event-agent .
docker run -p 8080:8080 -e AGENT_DEMO_MODE=true event-agent
```

Grounding search and function calling are never combined in a single Gemini request (`gemini_client.py`).
