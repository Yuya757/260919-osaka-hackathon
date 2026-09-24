import type {
  AgentRun,
  ApiEvent,
  ChatRequest,
  ChatResponse,
  EventClaimStartResponse,
  EventClaimVerifyResponse,
  EventEditResponse,
  EventRouteResponse,
  OrganizerEditValues,
  EvidenceListResponse,
  OrganizerPostCreateResponse,
  OrganizerPostListResponse,
  OrganizerPostPreviewResponse,
  OrganizerPostRequest,
  PoolSearchActivity,
  PoolSearchRequest,
  PoolSearchResponse,
  PoolSearchStreamEvent,
  SearchActivity,
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

/**
 * SSE の取り先。Firebase Hosting はストリームをまとめて返すので、本番は Cloud Run を
 * じかに呼ぶ（ビルド時に VITE_AGENT_STREAM_URL で渡す）。無ければ同じオリジン。
 */
const STREAM_BASE = (import.meta.env.VITE_AGENT_STREAM_URL as string | undefined)?.replace(/\/$/, '') ?? ''

/** SSE の途中で切れた。1 行でも届いていれば、問い合わせ方式に戻さずエラーにする */
export class PoolSearchStreamError extends Error {
  constructor(
    message: string,
    readonly receivedAny: boolean,
  ) {
    super(message)
  }
}

/**
 * プール探索を SSE で受ける。動きは届いた順に ``onActivity`` へ渡し、最後の結果を返す。
 * 繋がらない・途中で切れたときは PoolSearchStreamError（呼び出し側が問い合わせ方式に戻す）。
 */
export async function poolSearchStream(
  body: PoolSearchRequest,
  onActivity: (line: SearchActivity) => void,
): Promise<PoolSearchResponse> {
  let receivedAny = false
  let response: Response
  try {
    response = await fetch(`${STREAM_BASE}/api/pool-search/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new PoolSearchStreamError('探索のストリームに繋がりませんでした。', false)
  }
  if (!response.ok || !response.body) {
    throw new PoolSearchStreamError(await readErrorDetail(response), false)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE の 1 件は空行で区切られる
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
      const data = frame
        .split('\n')
        .filter((line) => line.startsWith('data: '))
        .map((line) => line.slice(6))
        .join('\n')
      if (!data) continue
      const event = JSON.parse(data) as PoolSearchStreamEvent
      if (event.type === 'activity') {
        receivedAny = true
        onActivity(event.activity)
      } else if (event.type === 'result') {
        return event.result
      } else {
        throw new PoolSearchStreamError(event.message, true)
      }
    }
  }
  throw new PoolSearchStreamError('探索の結果が届きませんでした。', receivedAny)
}

/** 探索中の動き。poolSearch と並行して読み、エージェントの処理を 1 行ずつ見せる */
export function getPoolSearchActivity(searchId: string): Promise<PoolSearchActivity> {
  return request<PoolSearchActivity>(
    `/api/pool-search/${encodeURIComponent(searchId)}/activity`,
  )
}

/** 主催者の申請を始める（ADR-013）。イベントページに書いてもらう確認コードが返る */
export function startEventClaim(eventId: string): Promise<EventClaimStartResponse> {
  return request<EventClaimStartResponse>('/api/event-claims', {
    method: 'POST',
    body: JSON.stringify({ eventId }),
  })
}

/** イベントページの確認コードを確かめてもらう。見つかれば編集用の鍵が一度だけ返る */
export function verifyEventClaim(claimId: string): Promise<EventClaimVerifyResponse> {
  return request<EventClaimVerifyResponse>('/api/event-claims/verify', {
    method: 'POST',
    body: JSON.stringify({ claimId }),
  })
}

export function editClaimedEvent(
  claimId: string,
  editToken: string,
  values: OrganizerEditValues,
): Promise<EventEditResponse> {
  return request<EventEditResponse>('/api/event-claims/edit', {
    method: 'POST',
    body: JSON.stringify({ claimId, editToken, values }),
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

export function getEventRoute(
  eventId: string,
  from: string,
  /** 到着駅。イベントの最寄駅が未確認のときに使う */
  to?: string,
): Promise<EventRouteResponse> {
  const query = `?from=${encodeURIComponent(from)}${to ? `&to=${encodeURIComponent(to)}` : ''}`
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
