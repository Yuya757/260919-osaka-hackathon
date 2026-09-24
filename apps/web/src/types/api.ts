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
  /**
   * Grounding の searchEntryPoint.renderedContent。Grounding由来の生成文を
   * 表示する画面は、このHTMLを無改変で描画する義務がある（§6.4）。
   * 再スタイル・切り抜き・折りたたみ・非表示は禁止。
   */
  searchSuggestionsHtml?: string | null
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

/** パイプラインの役割。UI の「エージェントの動き」で列にする */
export type RunAgent = 'planner' | 'searcher' | 'extractor' | 'organizer'

export type RunActivity = {
  agent: RunAgent
  message: string
  level?: 'info' | 'warn'
  at: string
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
  /** 終了済み・対象外・危険URLで除外された候補数（§6.6 rejected） */
  rejectedCount?: number
  duplicateCount?: number
  errorCount?: number
  errorMessage?: string | null
  startedAt?: string
  completedAt?: string | null
  expiresAt?: string
  /** 各役割が何をしたか。古い行から捨てられ、最大80行 */
  activity?: RunActivity[]
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

/** 機会の種別。絞り込みとラベル表の切り替えに使う（ジャンル拡張計画） */
export type EventKind =
  | 'hackathon'
  | 'contest'
  | 'accelerator'
  | 'cocreation'
  | 'exhibition'
  | 'subsidy'

/** 締切と実施日のあいだの節目（一次選考通過、最終審査会、結果発表など） */
export type EventMilestone = {
  label: string
  at: string
  precision: 'datetime' | 'date'
}

export type EventDates = {
  /** null は「未確認」。UIで「締切なし」と表現してはならない（§6.6）。 */
  applicationDeadline?: string | null
  /** 'date' のとき時刻を表示してはならない */
  applicationDeadlinePrecision?: DatePrecision
  /** 実施（開始）日時。締切だけが分かっている告知では null（ビジコン・補助金） */
  eventStart?: string | null
  eventStartPrecision?: DatePrecision
  eventEnd?: string | null
  milestones?: EventMilestone[]
  /** IANA timezone。表示は必ずこのタイムゾーンで解釈する。 */
  timezone: string
}

export type ValidationStatus = 'verified' | 'partial' | 'quarantined' | 'rejected'

export type EventRecommendation = {
  score: number
  reason: string
}

/**
 * 選別の状態。カレンダー登録状態は含めない（上位§6.2 の added_to_calendar は
 * 採用せず、§7.3 に従い googleCalendarEventIds で表現する）。
 */
export type EventLifecycleStatus = 'suggested' | 'bookmarked' | 'dismissed'

/** 登録済みカレンダー予定のID。未登録は null。 */
export type GoogleCalendarEventIds = {
  deadlineEventId?: string | null
  mainEventId?: string | null
}

export type EvidenceSourceType = 'official' | 'organizer' | 'aggregator' | 'other'

/** この根拠が裏付けている Event のフィールドパス */
export type SupportedField =
  | 'title'
  | 'summary'
  | 'organizer'
  | 'category'
  | 'location'
  | 'dates.eventStart'
  | 'dates.eventEnd'
  | 'dates.applicationDeadline'
  | 'officialUrl'
  | 'applicationUrl'

export type GroundingMetadata = {
  chunkIndex: number
  supportScore?: number | null
}

/** 根拠（§7.2）。excerpt は検証に必要な最小限の引用のみ。 */
export type Evidence = {
  evidenceId: string
  query?: string | null
  sourceUrl: string
  canonicalUrl?: string | null
  sourceType: EvidenceSourceType
  title?: string | null
  excerpt?: string | null
  supports: SupportedField[]
  retrievedAt: string
  groundingMetadata?: GroundingMetadata | null
  contentHash?: string | null
}

export type EvidenceListResponse = {
  eventId: string
  evidence: Evidence[]
}

/** 一覧に添える根拠の要約。全文は GET /api/events/{eventId}/evidence */
export type EvidencePreview = {
  sourceUrl: string
  sourceType: EvidenceSourceType
  supports: SupportedField[]
  excerpt: string
}

/** Event candidate / persisted event (§7.3) */
export type Event = {
  eventId: string
  userId: string
  title: string
  normalizedTitle: string
  summary: string
  category: string
  kind?: EventKind
  organizer?: string | null
  location: EventLocation
  dates: EventDates
  officialUrl: string
  applicationUrl?: string | null
  validationStatus: ValidationStatus
  /** アプリ側算出値。LLMの自己申告値ではない（§7.5） */
  confidence: number
  evidenceIds: string[]
  dedupKey: string
  recommendation?: EventRecommendation | null
  firstSeenAt: string
  lastSeenAt: string
  sourceRunId: string
  status: EventLifecycleStatus
  googleCalendarEventIds?: GoogleCalendarEventIds
  /** ジャンル固有の値（賞金・支援内容・対象ステージなど）。最大10項目 */
  attributes?: Record<string, string>
  /** 一覧用の根拠（サーバーが list 応答で添える）。最大4件 */
  evidencePreview?: EvidencePreview[]
  /** @deprecated Phase 1 の表示用文字列。Evidence.sourceType へ統合して廃止する。 */
  source?: string
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

// ---- 主催者投稿フィード（F-06）— packages/contracts/schemas/organizer-post.json

export type PostOrigin = 'organizer' | 'bot'
export type PostStatus = 'published' | 'hidden'
export type PlacementKind = 'normal' | 'pinned' | 'priority'

export type PostPlacement = {
  kind: PlacementKind
  until?: string | null
}

export type PostIssueCode =
  | 'EVENT_DATE_MISSING'
  | 'YEAR_AMBIGUOUS'
  | 'EVENT_FINISHED'
  | 'DATE_CONFLICT'
  | 'DEADLINE_MISSING'
  | 'DUPLICATE_OF_EVENT'

export type PostIssue = {
  code: PostIssueCode
  severity: 'error' | 'warning'
  message: string
}

export type OrganizerPostRequest = {
  organizerName: string
  contactUrl: string
  title: string
  body: string
}

/**
 * 投稿は派生した Event と根拠を埋め込む。Event そのものではなく、`events/` にも
 * 載らない（ADR-006）。`linkedEventId` は AI 収集イベントと同じと判定された相手。
 */
export type OrganizerPost = {
  postId: string
  userId: string
  origin: PostOrigin
  organizerName: string
  contactUrl: string
  title: string
  body: string
  event: Event
  evidence: Evidence[]
  status: PostStatus
  placement: PostPlacement
  linkedEventId?: string | null
  linkedDedupKey?: string | null
  injectionFlags: string[]
  /** 管理者が主催者の本人性を確認済み（ADR-009）。再投稿で戻らない */
  organizerConfirmed: boolean
  confirmedAt?: string | null
  createdAt: string
  updatedAt: string
}

/** 計測付きリダイレクトの種別（ADR-009） */
export type GoKind = 'official' | 'application' | 'contact'

export type MetricCounts = { clicks: number; calendar: number }

export type EventMetrics = {
  eventId: string
  clicks: { official: number; application: number; contact: number }
  calendar: number
  daily: Record<string, MetricCounts>
  updatedAt?: string | null
}

export type PostMetricsResponse = {
  postId: string
  eventId: string
  linkedEventId?: string | null
  metrics: EventMetrics
  linkedMetrics?: EventMetrics | null
}

export type OrganizerPostPreviewResponse = {
  event: Event | null
  linkedEvent: Event | null
  issues: PostIssue[]
}

export type OrganizerPostCreateResponse = {
  post: OrganizerPost
  warnings: PostIssue[]
}

export type OrganizerPostListResponse = {
  posts: OrganizerPost[]
}

// ---- プール探索エージェント（ADR-010）— packages/contracts/schemas/pool-search.json

export type SearchAgent = 'interpreter' | 'filter' | 'scorer' | 'presenter'

export type SearchActivity = {
  agent: SearchAgent
  message: string
  level?: 'info' | 'warn'
  at: string
}

export type SearchIntent = {
  interestsPrompt: string
  locations: string[]
  onlineOnly: boolean
  dateFrom?: string | null
  dateTo?: string | null
  keywords: string[]
  /** 問いかけが指す機会の種別。空なら種別で絞っていない */
  kinds: EventKind[]
}

export type PoolSearchRequest = {
  sessionId?: string
  query: string
  /** 渡すと動きが 1 行ずつ保存され、探索中でも getPoolSearchActivity で読める */
  searchId?: string
}

/** 探索中の動き。まだ 1 行も無ければ空配列 */
export type PoolSearchActivity = { searchId: string; activity: SearchActivity[] }

export type PoolSearchResponse = {
  sessionId: string
  /** 一覧の上に出す一言。Grounding 由来ではない（§3.7 の表示義務は生じない） */
  reply: string
  intent: SearchIntent
  events: Event[]
  activity: SearchActivity[]
  lastCollectedAt?: string | null
  modelCalls: number
}
