/** Mirrors packages/contracts/schemas — see docs/Agent詳細要件定義書.md §7–8 */

export type UserPreferences = {
  interestsPrompt: string
  targetYear: number
  onlineAllowed: boolean
  locations: string[]
}

export type ChatAction =
  | { type: 'agent_run_started'; runId: string }
  | { type: 'preferences_updated'; preferences: UserPreferences }
  | { type: 'events_ready'; count: number }

export type ChatRequest = {
  sessionId?: string
  message: string
}

export type ChatResponse = {
  sessionId: string
  reply: string
  actions?: ChatAction[]
}

export type AgentRunStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'partial_success'
  | 'failed'
  | 'cancelled'

export type AgentRunTriggerType = 'manual' | 'scheduled'

export type CreateAgentRunRequest = {
  forceRefresh?: boolean
}

export type CreateAgentRunResponse = {
  runId: string
  status: 'queued'
}

/** GET /api/agent-runs/{runId} — subset of Firestore agentRuns/{runId} (§7.1, §8.2) */
export type AgentRun = {
  runId: string
  userId?: string
  triggerType?: AgentRunTriggerType
  idempotencyKey?: string
  status: AgentRunStatus
  currentStep?: string
  model?: string
  queryCount?: number
  candidateCount?: number
  verifiedCount?: number
  partialCount?: number
  quarantinedCount?: number
  duplicateCount?: number
  errorCount?: number
  errorMessage?: string | null
  startedAt?: string
  completedAt?: string | null
  expiresAt?: string
}

export type EventLocationType = 'online' | 'offline' | 'hybrid' | 'unknown'

export type EventLocation = {
  type: EventLocationType
  venue?: string | null
  region?: string | null
  /** 会場の最寄駅名（経路検索の到着駅） */
  nearestStation?: string | null
}

export type DatePrecision = 'datetime' | 'date' | 'unknown'

export type EventDates = {
  applicationDeadline?: string | null
  applicationDeadlinePrecision?: DatePrecision
  eventStart: string
  eventStartPrecision?: 'datetime' | 'date'
  eventEnd?: string | null
  timezone: string
}

export type ValidationStatus = 'verified' | 'partial' | 'quarantined' | 'rejected'

export type EventRecommendation = {
  score: number
  reason: string
}

export type EventLifecycleStatus = 'suggested' | 'bookmarked' | 'dismissed'

/** Event candidate / persisted event (§7.3) */
export type Event = {
  eventId: string
  userId: string
  title: string
  normalizedTitle: string
  summary: string
  category: string
  organizer?: string | null
  location: EventLocation
  dates: EventDates
  officialUrl: string
  applicationUrl?: string
  validationStatus: ValidationStatus
  confidence: number
  evidenceIds: string[]
  dedupKey: string
  recommendation?: EventRecommendation
  firstSeenAt: string
  lastSeenAt: string
  sourceRunId: string
  status: EventLifecycleStatus
}

export type EventListResponse = {
  events: Event[]
}

/** API list view; same shape as Event (§8.3) */
export type ApiEvent = Event

/** packages/contracts/schemas/route.json — GET /api/events/{eventId}/route?from= */
export type Station = {
  code: string
  name: string
  prefecture?: string | null
}

export type RouteLeg = {
  line: string
  fromStation: string
  toStation: string
  departure?: string | null
  arrival?: string | null
  minutes?: number | null
}

export type RouteSummary = {
  fromStation: Station
  toStation: Station
  departure: string
  arrival: string
  totalMinutes: number
  transferCount: number
  fareYen?: number | null
  legs: RouteLeg[]
}

export type EventRouteResponse = {
  eventId: string
  arriveBy: string
  route: RouteSummary
}
