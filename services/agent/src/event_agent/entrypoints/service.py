from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, Header, HTTPException, Path, Query, Response
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from event_agent.agents.chat import handle_chat
from event_agent.config import get_settings
from event_agent.demo.catalog import demo_catalog
from event_agent.demo.evidence import demo_evidence
from event_agent.clients.ekispert import (
    EkispertError,
    EkispertNotConfigured,
    RouteNotFound,
    Station,
    StationNotFound,
    ekispert_client,
)
from event_agent.extraction.extractor import looks_like_address
from event_agent.schemas import (
    AgentRun,
    AgentRunCreateRequest,
    AgentRunCreateResponse,
    ApiEvent,
    ChatRequest,
    ChatResponse,
    EventClaimStartRequest,
    EventClaimStartResponse,
    EventClaimVerifyRequest,
    EventClaimVerifyResponse,
    EventEditRequest,
    EventEditResponse,
    EventRouteResponse,
    EventsResponse,
    EvidenceListResponse,
    HealthResponse,
    OrganizerPostCreateResponse,
    OrganizerPostListResponse,
    OrganizerPostPreviewResponse,
    OrganizerPostRequest,
    PoolSearchActivity,
    PoolSearchRequest,
    PoolSearchResponse,
    PostMetricsResponse,
    MetricEventRequest,
    preview_evidence,
)
from event_agent.storage.store import store
from event_agent.workflows.collect import schedule_collect_run
from event_agent.workflows.pool import ranked_pool
from event_agent.workflows.pool_search import search_pool
from event_agent.workflows.event_claims import ClaimError, edit_event, start_claim, verify_claim
from event_agent.domain.outbound import with_utm
from event_agent.workflows.organizer_posts import (
    PostNotFound,
    PostRejected,
    create_post,
    list_feed,
    outbound_url,
    post_metrics,
    preview_post,
)

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs (including API keys in query strings) at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title="Event Agent Service",
    version="0.1.0",
    description="Osaka hackathon MVP — event discovery agent (ADK-style workflow)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        demo_mode=not settings.use_vertex,
        model=settings.gemini_model if settings.use_vertex else None,
        manualRunsEnabled=settings.manual_runs_enabled,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    return await handle_chat(body)


@app.post("/api/agent-runs", response_model=AgentRunCreateResponse)
async def create_agent_run(
    body: AgentRunCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AgentRunCreateResponse:
    if not settings.manual_runs_enabled:
        # ユーザー起点の Grounding 探索は費用のため既定で受け付けない（ADR-008）
        raise HTTPException(
            status_code=403,
            detail="手動の探索は現在利用できません。毎朝の自動収集の結果を表示しています。",
        )
    session = store.get_or_create_session(body.session_id)
    run = schedule_collect_run(
        session.preferences,
        force_refresh=body.force_refresh,
        idempotency_key=idempotency_key,
    )
    return AgentRunCreateResponse(runId=run.run_id, status="queued")


@app.get("/api/agent-runs/{run_id}", response_model=AgentRun)
async def get_agent_run(run_id: str) -> AgentRun:
    record = store.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    return record


@app.get("/api/events", response_model=EventsResponse)
async def list_events(
    sourceRunId: str | None = Query(default=None),
    sessionId: str | None = Query(default=None),
) -> EventsResponse:
    """Displayable events (§8.3).

    ``sourceRunId`` を指定すればその Run の結果、無ければ共有プール（ADR-008）を
    ``sessionId`` の関心条件で採点した順に返す。どちらも quarantined / rejected は出さない。
    """
    now = datetime.now(timezone.utc)
    if sourceRunId:
        if not store.get_run(sourceRunId):
            raise HTTPException(status_code=404, detail="Run not found")
        events = [
            e
            for e in store.list_events(sourceRunId)
            if e.validation_status in ("verified", "partial")
        ]
        evidence_by_id = store.get_evidence_for_events(events)
    else:
        session = store.get_or_create_session(sessionId)
        events, evidence_by_id = ranked_pool(session.preferences, now=now)

    # 一覧の行に根拠（出典と引用）を添える。全文は evidence API
    with_preview = [
        e.model_copy(
            update={
                "evidence_preview": preview_evidence(
                    evidence_by_id.get(e.event_id) or demo_evidence().get(e.event_id, [])
                )
            }
        )
        for e in events
    ]
    return EventsResponse(events=with_preview, lastCollectedAt=store.latest_collection_at())


def _find_event(event_id: str) -> ApiEvent | None:
    stored = store.get_event(event_id)
    if stored:
        return stored
    # 主催者投稿由来のイベントは events/ に無い。投稿に埋め込まれた写しを使う（ADR-006）
    for post in store.list_organizer_posts(status="published"):
        if post.event.event_id == event_id:
            return post.event
    # デモカタログは保存されないことがあるため、最後に見る。
    for event in demo_catalog():
        if event.event_id == event_id:
            return event
    return None


@app.get("/api/events/{event_id}/evidence", response_model=EvidenceListResponse)
async def get_event_evidence(event_id: str) -> EvidenceListResponse:
    """根拠（§7.2）を返す。S-08 の根拠シートが使う。

    quarantined / rejected のイベントは通常UIへ出さないため、根拠も返さない（§8.3）。
    """
    event = _find_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.validation_status not in ("verified", "partial"):
        raise HTTPException(status_code=404, detail="Event not found")
    return EvidenceListResponse(
        eventId=event.event_id,
        evidence=store.get_evidence(event.source_run_id, event.evidence_ids),
    )


@app.get("/api/events/{event_id}/route", response_model=EventRouteResponse)
async def get_event_route(
    event_id: str,
    origin: str = Query(alias="from", min_length=1, max_length=40, description="出発駅名"),
    destination: str | None = Query(
        default=None, alias="to", min_length=1, max_length=40,
        description="到着駅名。省略時はイベントの最寄駅",
    ),
) -> EventRouteResponse:
    event = _find_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.location.type == "online":
        raise HTTPException(status_code=400, detail="オンライン開催のため経路検索はできません。")
    if event.dates.event_start is None:
        raise HTTPException(status_code=400, detail="実施日が未確認のため経路検索できません。")
    # 会場名（「グランフロント大阪」）を駅名として渡してはいけない。駅すぱあとは
    # 当然見つけられず「駅が見つかりません」になるだけ。住所なら住所検索に回す。
    destination_name = destination or event.location.nearest_station
    if not ekispert_client.configured:
        raise HTTPException(status_code=503, detail="経路検索は現在利用できません。")

    destination_station: Station | None = None
    if not destination_name:
        venue = event.location.venue or event.location.region
        if looks_like_address(venue):
            destination_station = await ekispert_client.find_station_near_address(venue or "")
    if destination_station is None and not destination_name:
        raise HTTPException(
            status_code=400,
            detail="会場の最寄駅が分かりません。到着駅を入力してください。",
        )

    try:
        origin_station = await ekispert_client.find_station(origin)
        if destination_station is None:
            destination_station = await ekispert_client.find_station(destination_name or "")
        route = await ekispert_client.search_route_arriving_by(
            origin_station, destination_station, event.dates.event_start
        )
    except EkispertNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except StationNotFound as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RouteNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EkispertError as exc:
        logger.warning("route search failed for %s: %s", event_id, exc)
        raise HTTPException(status_code=502, detail="経路検索サービスでエラーが発生しました。") from exc
    except httpx.HTTPError as exc:
        # 例外文には URL（＝アクセスキー）が入る。種別だけを残す
        logger.warning("route search transport error for %s: %s", event_id, type(exc).__name__)
        raise HTTPException(status_code=502, detail="経路検索サービスに接続できませんでした。") from exc

    return EventRouteResponse(eventId=event.event_id, arriveBy=event.dates.event_start, route=route)


# --------------------------------------------------------- event claims (ADR-013)


@app.post("/api/event-claims", response_model=EventClaimStartResponse)
async def create_event_claim(body: EventClaimStartRequest) -> EventClaimStartResponse:
    """主催者の申請を始め、イベントページに書いてもらう確認コードを返す。"""
    try:
        return start_claim(body.event_id, now=datetime.now(timezone.utc))
    except ClaimError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@app.post("/api/event-claims/verify", response_model=EventClaimVerifyResponse)
async def verify_event_claim(body: EventClaimVerifyRequest) -> EventClaimVerifyResponse:
    """イベントページを読み、確認コードがあれば編集用の鍵を返す（一度だけ）。"""
    try:
        return await verify_claim(body.claim_id, now=datetime.now(timezone.utc))
    except ClaimError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@app.post("/api/event-claims/edit", response_model=EventEditResponse)
async def edit_claimed_event(body: EventEditRequest) -> EventEditResponse:
    """鍵を確かめて、主催者の値（最寄駅・会場・申込締切・申込ページ）を持たせる。"""
    try:
        event = edit_event(
            body.claim_id, body.edit_token, body.values, now=datetime.now(timezone.utc)
        )
    except ClaimError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return EventEditResponse(event=event)


# ---------------------------------------------------------------- pool search


@app.get("/api/pool-search/{search_id}/activity", response_model=PoolSearchActivity)
async def pool_search_activity(
    search_id: str = Path(pattern=r"^[A-Za-z0-9-]{8,64}$"),
) -> PoolSearchActivity:
    """探索中の動き（ADR-010）。画面は探索のリクエストと並行してこれを読み、1 行ずつ出す。

    最初の 1 行が書かれる前に読まれることがあるので、無ければ 404 ではなく空で返す。
    """
    return PoolSearchActivity(
        searchId=search_id, activity=store.get_search_activity(search_id) or []
    )


@app.post("/api/pool-search", response_model=PoolSearchResponse)
async def pool_search(body: PoolSearchRequest) -> PoolSearchResponse:
    """プール探索エージェント（ADR-010）。Web には出ず、収集済みイベントを問いかけで探す。"""
    result = await search_pool(body.query, body.session_id, search_id=body.search_id)
    evidence_by_id = store.get_evidence_for_events(result.events)
    result.events = [
        e.model_copy(
            update={
                "evidence_preview": preview_evidence(
                    evidence_by_id.get(e.event_id) or demo_evidence().get(e.event_id, [])
                )
            }
        )
        for e in result.events
    ]
    return result


# ------------------------------------------------------------ organizer posts


@app.post("/api/organizer-posts/preview", response_model=OrganizerPostPreviewResponse)
async def preview_organizer_post(request: OrganizerPostRequest) -> OrganizerPostPreviewResponse:
    """投稿前の確認（F-06）。何も保存せず、抽出した日程と指摘だけを返す。"""
    try:
        draft, linked = preview_post(request, now=datetime.now(timezone.utc))
    except PostRejected as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return OrganizerPostPreviewResponse(event=draft.event, linkedEvent=linked, issues=draft.issues)


@app.post(
    "/api/organizer-posts",
    response_model=OrganizerPostCreateResponse,
    status_code=201,
)
async def create_organizer_post(request: OrganizerPostRequest) -> OrganizerPostCreateResponse:
    try:
        post, warnings = create_post(request, now=datetime.now(timezone.utc))
    except PostRejected as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return OrganizerPostCreateResponse(post=post, warnings=warnings)


@app.get("/api/organizer-posts", response_model=OrganizerPostListResponse)
async def list_organizer_posts() -> OrganizerPostListResponse:
    """フィード。公開中で開催前の投稿を、固定 → 優先 → 新しい順で返す。"""
    return OrganizerPostListResponse(posts=list_feed(now=datetime.now(timezone.utc)))


# -------------------------------------------------------------- metrics (ADR-009)

JST_OFFSET = timedelta(hours=9)


def _jst_date(now: datetime) -> str:
    return (now + JST_OFFSET).date().isoformat()


@app.get("/api/go/{event_id}/{kind}")
async def go_outbound(event_id: str, kind: str) -> RedirectResponse:
    """公式サイト・申込ページへの計測付きリダイレクト。

    宛先は保存済みの URL だけ（クエリで受け取らない）。CDN やブラウザが 302 を
    キャッシュしてカウンタを飛ばさないよう no-store。
    """
    if kind not in ("official", "application", "contact"):
        raise HTTPException(status_code=404, detail="Not found")
    event = _find_event(event_id)
    target = outbound_url(event, kind) if event else None
    if not target:
        raise HTTPException(status_code=404, detail="Not found")
    store.increment_event_metric(event_id, kind, jst_date=_jst_date(datetime.now(timezone.utc)))
    return RedirectResponse(
        with_utm(target, event_id), status_code=302, headers={"Cache-Control": "no-store"}
    )


@app.post("/api/events/{event_id}/metrics", status_code=204)
async def record_event_metric(event_id: str, body: MetricEventRequest) -> Response:
    """カレンダー登録の計測。登録そのものは端末側のモックで行われる。"""
    if not _find_event(event_id):
        raise HTTPException(status_code=404, detail="Event not found")
    store.increment_event_metric(event_id, body.kind, jst_date=_jst_date(datetime.now(timezone.utc)))
    return Response(status_code=204)


@app.get("/api/organizer-posts/{post_id}/metrics", response_model=PostMetricsResponse)
async def get_post_metrics(post_id: str) -> PostMetricsResponse:
    """投稿の成果（認証は未導入なので公開。ADR-009）。"""
    try:
        return post_metrics(post_id)
    except PostNotFound as exc:
        raise HTTPException(status_code=404, detail="Post not found") from exc
