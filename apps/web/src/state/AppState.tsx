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
import { AgentRunPendingError, listEvents, pollAgentRun, startAgentRun } from '../api/client'
import { displayable } from '../lib/eventView'
import { loadRegistrations, registerToCalendar, unregisterFromCalendar } from '../lib/calendarMock'
import type { CalendarSelection } from '../lib/calendarMock'
import type { AgentRun, Event, GoogleCalendarEventIds } from '../types/api'

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

type AppState = {
  events: Event[]
  loadState: LoadState
  loadError: string | null
  run: AgentRun | null
  runPending: boolean
  saved: Record<string, boolean>
  calendar: Record<string, GoogleCalendarEventIds>
  refresh: () => Promise<void>
  startRun: () => Promise<void>
  toggleSaved: (eventId: string) => void
  register: (event: Event, selection: CalendarSelection) => Promise<void>
  unregister: (eventId: string) => Promise<void>
  eventById: (eventId: string) => Event | undefined
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
  const runningRef = useRef(false)

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

  useEffect(() => {
    void refresh()
  }, [refresh])

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
  }, [refresh])

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

  const eventById = useCallback(
    (eventId: string) => events.find((event) => event.eventId === eventId),
    [events],
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
      refresh: () => refresh(),
      startRun,
      toggleSaved,
      register,
      unregister,
      eventById,
    }),
    [
      events,
      loadState,
      loadError,
      run,
      runPending,
      saved,
      calendar,
      refresh,
      startRun,
      toggleSaved,
      register,
      unregister,
      eventById,
    ],
  )

  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useAppState(): AppState {
  const value = useContext(Context)
  if (!value) throw new Error('useAppState must be used inside AppStateProvider')
  return value
}
