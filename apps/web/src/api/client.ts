import type {
  AgentRun,
  ApiEvent,
  ChatRequest,
  ChatResponse,
  EventRouteResponse,
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

export function startAgentRun(forceRefresh = false): Promise<AgentRun> {
  return request<AgentRun>('/api/agent-runs', {
    method: 'POST',
    body: JSON.stringify({ forceRefresh }),
  })
}

export function getAgentRun(runId: string): Promise<AgentRun> {
  return request<AgentRun>(`/api/agent-runs/${runId}`)
}

export function listEvents(sourceRunId?: string): Promise<{ events: ApiEvent[] }> {
  const query = sourceRunId ? `?sourceRunId=${encodeURIComponent(sourceRunId)}` : ''
  return request<{ events: ApiEvent[] }>(`/api/events${query}`)
}

export function getEventRoute(eventId: string, from: string): Promise<EventRouteResponse> {
  const query = `?from=${encodeURIComponent(from)}`
  return request<EventRouteResponse>(`/api/events/${encodeURIComponent(eventId)}/route${query}`)
}

export async function pollAgentRun(
  runId: string,
  onUpdate?: (run: AgentRun) => void,
  timeoutMs = 120_000,
): Promise<AgentRun> {
  const started = Date.now()
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
    await new Promise((resolve) => window.setTimeout(resolve, 1200))
  }
  throw new Error('エージェント実行がタイムアウトしました')
}
