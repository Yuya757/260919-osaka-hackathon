import type { AgentRun, ApiEvent, ChatRequest, ChatResponse } from '../types/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `API error ${response.status}`)
  }

  return response.json() as Promise<T>
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
