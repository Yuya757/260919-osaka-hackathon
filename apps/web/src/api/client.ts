import type {
  AgentRun,
  ApiEvent,
  ChatRequest,
  ChatResponse,
  EventRouteResponse,
  EvidenceListResponse,
  OrganizerPostCreateResponse,
  OrganizerPostListResponse,
  OrganizerPostPreviewResponse,
  OrganizerPostRequest,
  PoolSearchRequest,
  PoolSearchResponse,
  GoKind,
  PostMetricsResponse,
} from '../types/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    throw new Error(await readErrorDetail(response))
  }

  return response.json() as Promise<T>
}

/** FastAPI returns `{ detail }` for HTTPException; fall back to the raw body. */
async function readErrorDetail(response: Response): Promise<string> {
  const text = await response.text()
  try {
    const parsed = JSON.parse(text) as { detail?: unknown }
    if (typeof parsed.detail === 'string') return parsed.detail
  } catch {
    // not JSON
  }
  return text || `API error ${response.status}`
}

export function sendChat(body: ChatRequest): Promise<ChatResponse> {
  return request<ChatResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function startAgentRun(
  forceRefresh = false,
  idempotencyKey?: string,
  sessionId?: string,
): Promise<AgentRun> {
  return request<AgentRun>('/api/agent-runs', {
    method: 'POST',
    // 同一操作の二重実行を防ぐ（§9.3）。未指定ならサーバが発行する。
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    // チャットで更新した関心条件を Run に引き継ぐ
    body: JSON.stringify({ forceRefresh, sessionId }),
  })
}

export function getAgentRun(runId: string): Promise<AgentRun> {
  return request<AgentRun>(`/api/agent-runs/${runId}`)
}

export type EventListResponse = { events: ApiEvent[]; lastCollectedAt?: string | null }

/**
 * 一覧。`sourceRunId` を渡せばその Run の結果、無ければ共有プール（ADR-008）を
 * `sessionId` の関心条件で採点した順に返す。
 */
export function listEvents(sourceRunId?: string, sessionId?: string): Promise<EventListResponse> {
  const params = new URLSearchParams()
  if (sourceRunId) params.set('sourceRunId', sourceRunId)
  if (sessionId) params.set('sessionId', sessionId)
  const query = params.toString()
  return request<EventListResponse>(`/api/events${query ? `?${query}` : ''}`)
}

/** プール探索エージェント（ADR-010）。Web には出ず、収集済みイベントを問いかけで探す。 */
export function poolSearch(body: PoolSearchRequest): Promise<PoolSearchResponse> {
  return request<PoolSearchResponse>('/api/pool-search', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export type HealthResponse = { status: string; demo_mode: boolean; model?: string | null; manualRunsEnabled: boolean }

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/api/health')
}

/** 根拠（§7.2）。S-08 の根拠シートが使う。 */
export function listEvidence(eventId: string): Promise<EvidenceListResponse> {
  return request<EvidenceListResponse>(
    `/api/events/${encodeURIComponent(eventId)}/evidence`,
  )
}

export function getEventRoute(eventId: string, from: string): Promise<EventRouteResponse> {
  const query = `?from=${encodeURIComponent(from)}`
  return request<EventRouteResponse>(`/api/events/${encodeURIComponent(eventId)}/route${query}`)
}

/** 主催者投稿フィード（F-06）。 */
export function listOrganizerPosts(): Promise<OrganizerPostListResponse> {
  return request<OrganizerPostListResponse>('/api/organizer-posts')
}

/** 投稿前の確認。何も保存しない。 */
export function previewOrganizerPost(
  body: OrganizerPostRequest,
): Promise<OrganizerPostPreviewResponse> {
  return request<OrganizerPostPreviewResponse>('/api/organizer-posts/preview', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function createOrganizerPost(
  body: OrganizerPostRequest,
): Promise<OrganizerPostCreateResponse> {
  return request<OrganizerPostCreateResponse>('/api/organizer-posts', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/**
 * 外部リンクは計測付きリダイレクト（ADR-009）を経由する。サーバーが保存済みの URL へ
 * 302 で送り、utm を付ける。href にそのまま使う。
 */
export function goUrl(eventId: string, kind: GoKind): string {
  return `/api/go/${encodeURIComponent(eventId)}/${kind}`
}

/** カレンダー登録の計測。登録自体は端末側で済んでいるので、失敗しても呼び出し側は無視する。 */
export function postEventMetric(eventId: string, kind: 'calendar'): Promise<void> {
  return fetch(`/api/events/${encodeURIComponent(eventId)}/metrics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind }),
  }).then(() => undefined)
}

export function getPostMetrics(postId: string): Promise<PostMetricsResponse> {
  return request<PostMetricsResponse>(`/api/organizer-posts/${encodeURIComponent(postId)}/metrics`)
}

/** Runが時間内に終わらなかったことを表す。失敗とは区別して扱う。 */
export class AgentRunPendingError extends Error {
  constructor(readonly runId: string) {
    super('まだ実行中です。しばらくしてから状態を再確認してください。')
    this.name = 'AgentRunPendingError'
  }
}

/**
 * ポーリング間隔。最初は短く、その後伸ばす。
 * 1.2秒固定だと120秒で約100リクエストになる。
 */
function pollDelay(attempt: number): number {
  if (attempt < 10) return 1_000
  if (attempt < 25) return 2_000
  return 5_000
}

/**
 * Runが終端状態になるまでポーリングする。
 *
 * 既定の180秒は、§11.1 のp95目標120秒と §16 の RUN_TIMEOUT_SECONDS=300 の
 * あいだを取ったもの。120秒はp95目標であって上限ではないため、そこで
 * 打ち切るとサーバがまだ実行中なのにクライアントだけが諦めることになる。
 * 時間切れは失敗ではないので、専用の AgentRunPendingError を投げる。
 */
export async function pollAgentRun(
  runId: string,
  onUpdate?: (run: AgentRun) => void,
  timeoutMs = 180_000,
): Promise<AgentRun> {
  const started = Date.now()
  let attempt = 0
  while (Date.now() - started < timeoutMs) {
    const run = await getAgentRun(runId)
    onUpdate?.(run)
    if (
      run.status === 'succeeded' ||
      run.status === 'partial_success' ||
      run.status === 'failed' ||
      run.status === 'cancelled'
    ) {
      return run
    }
    await new Promise((resolve) => window.setTimeout(resolve, pollDelay(attempt)))
    attempt += 1
  }
  throw new AgentRunPendingError(runId)
}
