/**
 * アプリ全体で共有する状態。
 *
 * Runの進捗は全タブ共通のバナーで見せる必要があり（画面設計書 §2.2）、
 * チャットを閉じても追えなければならないので、画面ではなくここに置く。
 */
import { loadCachedEvents, saveCachedEvents } from '../lib/eventsCache'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  AgentRunPendingError,
  createOrganizerPost,
  getCalendarCounts,
  getHealth,
  listEvents,
  postEventMetric,
  listOrganizerPosts,
  pollAgentRun,
  getPoolSearchActivity,
  poolSearch,
  poolSearchStream,
  PoolSearchStreamError,
  startAgentRun,
} from '../api/client'
import { displayable } from '../lib/eventView'
import { loadRegistrations, registerToCalendar, unregisterFromCalendar } from '../lib/calendarMock'
import type { CalendarSelection } from '../lib/calendarMock'
import type {
  AgentRun,
  Event,
  GoogleCalendarEventIds,
  OrganizerPost,
  OrganizerPostCreateResponse,
  OrganizerPostRequest,
  PoolSearchResponse,
  SearchActivity,
} from '../types/api'

const SAVED_KEY = 'event-agent-saved-v1'

function readSaved(): Record<string, boolean> {
  try {
    const raw = window.localStorage.getItem(SAVED_KEY)
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {}
  } catch {
    return {}
  }
}

export type LoadState = 'idle' | 'loading' | 'ready' | 'error'

/**
 * 一覧最上部の入力欄から送った問いかけへの、プール探索エージェントの直近の応答
 * （ADR-010）。Grounding 由来ではないので Search Suggestions の表示義務は無い。
 */
export type AgentReply = {
  text: string
  activity: SearchActivity[]
}

type AppState = {
  events: Event[]
  loadState: LoadState
  /** 前回分を出したまま、裏で一覧を取り直している */
  refreshing: boolean
  loadError: string | null
  run: AgentRun | null
  runPending: boolean
  saved: Record<string, boolean>
  calendar: Record<string, GoogleCalendarEventIds>
  /** イベントごとのカレンダー登録数（全利用者の合計）。「N人が登録」に使う */
  calendarCounts: Record<string, number>
  /** 一覧の絞り込み文字列。ホームと保存で共有する */
  query: string
  setQuery: (query: string) => void
  agentReply: AgentReply | null
  agentPending: boolean
  refresh: () => Promise<void>
  startRun: () => Promise<void>
  /** 入力欄の内容でプールを探す（ADR-010）。Web には出ない */
  ask: (message: string) => Promise<void>
  /** ユーザー起点の Grounding 探索を受け付けるか（ADR-008）。false なら「探す」は並べ替え */
  manualRunsEnabled: boolean
  /** 共有プールに最後に収集が保存された時刻 */
  lastCollectedAt: string | null
  /** 主催者投稿フィード（F-06）。AI 収集の一覧とは別に持つ */
  posts: OrganizerPost[]
  postsState: LoadState
  postsError: string | null
  refreshPosts: () => Promise<void>
  createPost: (body: OrganizerPostRequest) => Promise<OrganizerPostCreateResponse>
  toggleSaved: (eventId: string) => void
  register: (event: Event, selection: CalendarSelection) => Promise<void>
  unregister: (eventId: string) => Promise<void>
  eventById: (eventId: string) => Event | undefined
  /** その Event が主催者投稿由来なら、その投稿 */
  postByEventId: (eventId: string) => OrganizerPost | undefined
}

const Context = createContext<AppState | null>(null)

/** 探索中の動きを読みにいく間隔 */
const ACTIVITY_POLL_MS = 500

function newSearchId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

export function AppStateProvider({ children }: { children: ReactNode }) {
  // 前回の一覧があれば、開いた瞬間に出す。取り直しは裏で行う
  const [cached] = useState(() => loadCachedEvents())
  const [events, setEvents] = useState<Event[]>(() => displayable(cached?.events ?? []))
  const [loadState, setLoadState] = useState<LoadState>(cached ? 'ready' : 'idle')
  const [refreshing, setRefreshing] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [run, setRun] = useState<AgentRun | null>(null)
  const [runPending, setRunPending] = useState(false)
  const [saved, setSaved] = useState<Record<string, boolean>>(() => readSaved())
  const [calendar, setCalendar] = useState<Record<string, GoogleCalendarEventIds>>(() =>
    loadRegistrations(),
  )
  const [calendarCounts, setCalendarCounts] = useState<Record<string, number>>({})
  const calendarRef = useRef(calendar)
  calendarRef.current = calendar
  const [query, setQuery] = useState('')
  const [agentReply, setAgentReply] = useState<AgentReply | null>(null)
  const [agentPending, setAgentPending] = useState(false)
  const sessionRef = useRef<string | undefined>(undefined)
  const runningRef = useRef(false)
  const [posts, setPosts] = useState<OrganizerPost[]>([])
  const [postsState, setPostsState] = useState<LoadState>('idle')
  const [postsError, setPostsError] = useState<string | null>(null)
  const [manualRunsEnabled, setManualRunsEnabled] = useState(true)
  const [lastCollectedAt, setLastCollectedAt] = useState<string | null>(
    cached?.lastCollectedAt ?? null,
  )

  useEffect(() => {
    getHealth()
      .then((health) => setManualRunsEnabled(health.manualRunsEnabled))
      .catch(() => {
        // 取れなければ「探す」は探索扱いのまま。サーバー側が 403 で止める
      })
  }, [])

  const refresh = useCallback(async (sourceRunId?: string) => {
    setLoadState((current) => (current === 'ready' ? current : 'loading'))
    setRefreshing(true)
    try {
      // 共有プールはセッションの関心条件で採点される
      const result = await listEvents(sourceRunId, sourceRunId ? undefined : sessionRef.current)
      const shown = displayable(result.events)
      setEvents(shown)
      setLastCollectedAt(result.lastCollectedAt ?? null)
      setLoadError(null)
      setLoadState('ready')
      if (!sourceRunId) saveCachedEvents(shown, result.lastCollectedAt ?? null)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'イベントを取得できませんでした。')
      // 前回分を出しているなら、それを消してまでエラーにしない
      setLoadState((current) => (current === 'ready' ? current : 'error'))
    } finally {
      setRefreshing(false)
    }
  }, [])

  const refreshPosts = useCallback(async () => {
    setPostsState((current) => (current === 'ready' ? current : 'loading'))
    try {
      const result = await listOrganizerPosts()
      setPosts(result.posts)
      setPostsError(null)
      setPostsState('ready')
    } catch (error) {
      setPostsError(error instanceof Error ? error.message : '投稿を取得できませんでした。')
      setPostsState('error')
    }
  }, [])

  useEffect(() => {
    void refresh()
    void refreshPosts()
    getCalendarCounts()
      .then((result) => setCalendarCounts(result.counts))
      .catch(() => {
        // 人数が読めなくても一覧は出す。人数の表示が無くなるだけ
      })
  }, [refresh, refreshPosts])

  useEffect(() => {
    try {
      window.localStorage.setItem(SAVED_KEY, JSON.stringify(saved))
    } catch {
      // 保存できなくても動作は続ける
    }
  }, [saved])

  const startRun = useCallback(async () => {
    if (runningRef.current) return
    runningRef.current = true
    setRunPending(false)
    try {
      const created = await startAgentRun(true, undefined, sessionRef.current)
      setRun({ ...created, status: 'queued', currentStep: 'queued' })
      const finished = await pollAgentRun(created.runId, (progress) => setRun(progress))
      setRun(finished)
      if (finished.status !== 'failed') {
        // Run の結果だけでなく共有プール全体（ADR-008）を関心順で取り直す
        await refresh()
        // Run の save ステップでボット投稿が流れるので、フィードも取り直す
        await refreshPosts()
      }
    } catch (error) {
      if (error instanceof AgentRunPendingError) {
        // 時間切れは失敗ではない。サーバ側ではまだ動いている可能性がある。
        setRunPending(true)
      } else {
        setRun((current) =>
          current
            ? {
                ...current,
                status: 'failed',
                errorMessage:
                  error instanceof Error ? error.message : '探索に失敗しました。',
              }
            : current,
        )
      }
    } finally {
      runningRef.current = false
    }
  }, [refresh, refreshPosts])

  const createPost = useCallback(
    async (body: OrganizerPostRequest) => {
      const created = await createOrganizerPost(body)
      await refreshPosts()
      return created
    },
    [refreshPosts],
  )

  /**
   * 「探す」= プール探索エージェント（ADR-010）。Web には出ず、毎朝の収集で貯めた
   * イベントを問いかけで解釈 → 絞り込み → 採点 → 提示する。文に「探して」と
   * 書かなくてもよく、空なら現在の関心条件で並べ直す。
   */
  /**
   * 問い合わせ方式（SSE が使えないときの控え）。探索のリクエストは終わるまで返らないので、
   * そのあいだ保存された動きを 0.5 秒ごとに読みにいく。
   */
  const searchWithPolling = useCallback(async (query: string): Promise<PoolSearchResponse> => {
    const searchId = newSearchId()
    let finished = false
    const poll = window.setInterval(() => {
      getPoolSearchActivity(searchId)
        .then(({ activity }) => {
          if (!finished && activity.length) setAgentReply({ text: '', activity })
        })
        .catch(() => {
          // 途中経過が読めなくても、最後の応答でまとめて出る
        })
    }, ACTIVITY_POLL_MS)
    try {
      return await poolSearch({ sessionId: sessionRef.current, query, searchId })
    } finally {
      finished = true
      window.clearInterval(poll)
    }
  }, [])

  const ask = useCallback(
    async (message: string) => {
      if (agentPending) return
      setAgentPending(true)
      setAgentReply({ text: '', activity: [] })
      const query = message.trim()
      try {
        // エージェントの動きは SSE で届いた順に出す。繋がらなければ問い合わせ方式に戻す
        let result: PoolSearchResponse
        try {
          const lines: SearchActivity[] = []
          result = await poolSearchStream({ sessionId: sessionRef.current, query }, (line) => {
            lines.push(line)
            setAgentReply({ text: '', activity: [...lines] })
          })
        } catch (error) {
          if (!(error instanceof PoolSearchStreamError) || error.receivedAny) throw error
          result = await searchWithPolling(query)
        }
        sessionRef.current = result.sessionId
        setAgentReply({ text: result.reply, activity: result.activity })
        setEvents(displayable(result.events))
        setLastCollectedAt(result.lastCollectedAt ?? null)
        setLoadError(null)
        setLoadState('ready')
      } catch (error) {
        setAgentReply({
          text:
            error instanceof Error
              ? `接続に失敗しました: ${error.message}`
              : 'エージェントに接続できませんでした。',
          activity: [],
        })
      } finally {
        setAgentPending(false)
      }
    },
    [agentPending, searchWithPolling],
  )

  const toggleSaved = useCallback((eventId: string) => {
    setSaved((current) => ({ ...current, [eventId]: !current[eventId] }))
  }, [])

  const register = useCallback(async (event: Event, selection: CalendarSelection) => {
    // 登録内容の変更は新しい登録として数えない。数えると「N人が登録」が水増しになる
    const first = !calendarRef.current[event.eventId]
    const ids = await registerToCalendar(event, selection)
    setCalendar((current) => ({ ...current, [event.eventId]: ids }))
    if (!first) return
    setCalendarCounts((current) => ({
      ...current,
      [event.eventId]: (current[event.eventId] ?? 0) + 1,
    }))
    // 成果の計測（ADR-009）。計測に失敗しても登録は済んでいるので無視する
    postEventMetric(event.eventId, 'calendar').catch(() => undefined)
  }, [])

  const unregister = useCallback(async (eventId: string) => {
    await unregisterFromCalendar(eventId)
    setCalendar((current) => {
      const next = { ...current }
      delete next[eventId]
      return next
    })
  }, [])

  // 投稿由来の Event は events には無いので、投稿側も探す（/events/:id を開けるように）
  // ボット投稿は AI 収集イベントの写しなので「投稿由来」には数えない。
  // 数えると AI イベントの詳細が投稿扱いになり、根拠が空（投稿は根拠を持たない）になる
  const postByEventId = useCallback(
    (eventId: string) =>
      posts.find((post) => post.origin === 'organizer' && post.event.eventId === eventId),
    [posts],
  )

  // 投稿（ボット投稿を含む）にしか無いイベントも開けるようにする
  const eventById = useCallback(
    (eventId: string) =>
      events.find((event) => event.eventId === eventId) ??
      posts.find((post) => post.event.eventId === eventId)?.event,
    [events, posts],
  )

  const value = useMemo<AppState>(
    () => ({
      events,
      loadState,
      refreshing,
      loadError,
      run,
      runPending,
      saved,
      calendar,
      calendarCounts,
      query,
      setQuery,
      agentReply,
      agentPending,
      refresh: () => refresh(),
      startRun,
      ask,
      manualRunsEnabled,
      lastCollectedAt,
      posts,
      postsState,
      postsError,
      refreshPosts,
      createPost,
      toggleSaved,
      register,
      unregister,
      eventById,
      postByEventId,
    }),
    [
      events,
      loadState,
      refreshing,
      loadError,
      run,
      runPending,
      saved,
      calendar,
      calendarCounts,
      query,
      agentReply,
      agentPending,
      refresh,
      startRun,
      ask,
      manualRunsEnabled,
      lastCollectedAt,
      posts,
      postsState,
      postsError,
      refreshPosts,
      createPost,
      toggleSaved,
      register,
      unregister,
      eventById,
      postByEventId,
    ],
  )

  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useAppState(): AppState {
  const value = useContext(Context)
  if (!value) throw new Error('useAppState must be used inside AppStateProvider')
  return value
}
