/**
 * アプリ全体で共有する状態。
 *
 * Runの進捗は全タブ共通のバナーで見せる必要があり（画面設計書 §2.2）、
 * チャットを閉じても追えなければならないので、画面ではなくここに置く。
 */
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
  listEvents,
  listOrganizerPosts,
  pollAgentRun,
  sendChat,
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
 * 一覧最上部の入力欄から送った問いかけへの、エージェントの直近の応答。
 * Grounding 由来の生成文なので、Search Suggestions の HTML も一緒に持つ（§6.4）。
 */
export type AgentReply = {
  text: string
  searchSuggestionsHtml?: string | null
}

type AppState = {
  events: Event[]
  loadState: LoadState
  loadError: string | null
  run: AgentRun | null
  runPending: boolean
  saved: Record<string, boolean>
  calendar: Record<string, GoogleCalendarEventIds>
  /** 一覧の絞り込み文字列。ホームと保存で共有する */
  query: string
  setQuery: (query: string) => void
  agentReply: AgentReply | null
  agentPending: boolean
  refresh: () => Promise<void>
  startRun: () => Promise<void>
  /** 入力欄の内容をエージェントに送る。Run が始まれば進捗はバナーで追える */
  ask: (message: string) => Promise<void>
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

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [events, setEvents] = useState<Event[]>([])
  const [loadState, setLoadState] = useState<LoadState>('idle')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [run, setRun] = useState<AgentRun | null>(null)
  const [runPending, setRunPending] = useState(false)
  const [saved, setSaved] = useState<Record<string, boolean>>(() => readSaved())
  const [calendar, setCalendar] = useState<Record<string, GoogleCalendarEventIds>>(() =>
    loadRegistrations(),
  )
  const [query, setQuery] = useState('')
  const [agentReply, setAgentReply] = useState<AgentReply | null>(null)
  const [agentPending, setAgentPending] = useState(false)
  const sessionRef = useRef<string | undefined>(undefined)
  const runningRef = useRef(false)
  const [posts, setPosts] = useState<OrganizerPost[]>([])
  const [postsState, setPostsState] = useState<LoadState>('idle')
  const [postsError, setPostsError] = useState<string | null>(null)

  const refresh = useCallback(async (sourceRunId?: string) => {
    setLoadState((current) => (current === 'ready' ? current : 'loading'))
    try {
      const result = await listEvents(sourceRunId)
      setEvents(displayable(result.events))
      setLoadError(null)
      setLoadState('ready')
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'イベントを取得できませんでした。')
      setLoadState('error')
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
      const created = await startAgentRun(true)
      setRun({ ...created, status: 'queued', currentStep: 'queued' })
      const finished = await pollAgentRun(created.runId, (progress) => setRun(progress))
      setRun(finished)
      if (finished.status !== 'failed') {
        await refresh(finished.runId)
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

  const ask = useCallback(
    async (message: string) => {
      const trimmed = message.trim()
      if (!trimmed || agentPending) return
      setAgentPending(true)
      try {
        const response = await sendChat({ sessionId: sessionRef.current, message: trimmed })
        sessionRef.current = response.sessionId
        setAgentReply({
          text: response.reply,
          searchSuggestionsHtml: response.searchSuggestionsHtml,
        })
        for (const action of response.actions ?? []) {
          // Run の完了は待たない。進捗は全画面共通のバナーで見せる
          if (action.type === 'agent_run_started') void startRun()
          if (action.type === 'events_ready') await refresh()
        }
      } catch (error) {
        setAgentReply({
          text:
            error instanceof Error
              ? `接続に失敗しました: ${error.message}`
              : 'エージェントに接続できませんでした。',
        })
      } finally {
        setAgentPending(false)
      }
    },
    [agentPending, refresh, startRun],
  )

  const toggleSaved = useCallback((eventId: string) => {
    setSaved((current) => ({ ...current, [eventId]: !current[eventId] }))
  }, [])

  const register = useCallback(async (event: Event, selection: CalendarSelection) => {
    const ids = await registerToCalendar(event, selection)
    setCalendar((current) => ({ ...current, [event.eventId]: ids }))
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
  const postByEventId = useCallback(
    (eventId: string) => posts.find((post) => post.event.eventId === eventId),
    [posts],
  )

  const eventById = useCallback(
    (eventId: string) =>
      events.find((event) => event.eventId === eventId) ?? postByEventId(eventId)?.event,
    [events, postByEventId],
  )

  const value = useMemo<AppState>(
    () => ({
      events,
      loadState,
      loadError,
      run,
      runPending,
      saved,
      calendar,
      query,
      setQuery,
      agentReply,
      agentPending,
      refresh: () => refresh(),
      startRun,
      ask,
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
      loadError,
      run,
      runPending,
      saved,
      calendar,
      query,
      agentReply,
      agentPending,
      refresh,
      startRun,
      ask,
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
