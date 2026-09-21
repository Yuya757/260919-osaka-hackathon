/** S-01 ホーム / イベント一覧 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { daysUntil, isFinished, isUrgent } from '../lib/eventView'
import { isRunning } from '../lib/runSteps'
import { EventCard } from '../components/EventCard'
import { CalendarSheet } from '../components/CalendarSheet'
import { RunProgressBanner } from '../components/RunProgressBanner'
import { SparkIcon } from '../components/Icon'
import type { Event } from '../types/api'

type Filter = 'all' | 'soon' | 'online' | 'check'

const FILTERS: [Filter, string][] = [
  ['all', 'すべて'],
  ['soon', '締切間近'],
  ['online', 'オンライン可'],
  ['check', '要確認'],
]

export function HomeScreen() {
  const { events, loadState, loadError, run, startRun, saved, calendar, toggleSaved, register, refresh } =
    useAppState()
  const [filter, setFilter] = useState<Filter>('all')
  const [sheetEvent, setSheetEvent] = useState<Event | null>(null)
  const navigate = useNavigate()

  const upcoming = useMemo(() => events.filter((event) => !isFinished(event)), [events])

  const visible = useMemo(() => {
    if (filter === 'soon') return upcoming.filter((event) => isUrgent(event))
    if (filter === 'online') return upcoming.filter((event) => event.location.type !== 'offline')
    if (filter === 'check') return upcoming.filter((event) => event.validationStatus === 'partial')
    return upcoming
  }, [upcoming, filter])

  const nextDeadline = useMemo(() => {
    return upcoming
      .filter((event) => isUrgent(event, 60))
      .sort(
        (a, b) =>
          (daysUntil(a.dates.applicationDeadline, a.dates.timezone) ?? 0) -
          (daysUntil(b.dates.applicationDeadline, b.dates.timezone) ?? 0),
      )[0]
  }, [upcoming])

  const verifiedCount = upcoming.filter((e) => e.validationStatus === 'verified').length
  const partialCount = upcoming.length - verifiedCount
  const busy = isRunning(run?.status)

  const today = new Date().toLocaleDateString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  })

  return (
    <>
      <header className="app-header">
        <div className="header-main">
          <p className="header-eyebrow">{today}</p>
          <h1>見逃したくない予定</h1>
        </div>
        <button
          type="button"
          className="primary-button"
          disabled={busy}
          onClick={() => void startRun()}
        >
          <SparkIcon />
          {busy ? '探索中…' : '更新'}
        </button>
      </header>

      <RunProgressBanner />

      <div className="scroll-area">
        {nextDeadline && (
          <section className="hero">
            <p className="hero-label">次の申込締切まで</p>
            <p className="hero-count">
              <strong>
                {String(
                  daysUntil(
                    nextDeadline.dates.applicationDeadline,
                    nextDeadline.dates.timezone,
                  ) ?? 0,
                ).padStart(2, '0')}
              </strong>
              <span>日</span>
            </p>
            <button
              type="button"
              className="hero-title"
              onClick={() => navigate(`/events/${encodeURIComponent(nextDeadline.eventId)}`)}
            >
              {nextDeadline.title}
            </button>
          </section>
        )}

        <div className="filters" role="group" aria-label="イベントの絞り込み">
          {FILTERS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>

        {loadState === 'loading' && (
          <div className="list">
            {[0, 1, 2].map((i) => (
              <div className="skeleton-card" key={i} aria-hidden="true" />
            ))}
          </div>
        )}

        {loadState === 'error' && (
          <div className="empty">
            <strong>イベントを取得できませんでした</strong>
            <p>{loadError}</p>
            <button type="button" className="primary-button" onClick={() => void refresh()}>
              再試行
            </button>
          </div>
        )}

        {loadState === 'ready' && (
          <>
            <p className="count-row">
              {upcoming.length}件 · 公式確認済み{verifiedCount} · 要確認{partialCount}
            </p>

            {visible.length === 0 ? (
              <div className="empty">
                <strong>
                  {upcoming.length === 0
                    ? 'まだイベントがありません'
                    : '条件に合うイベントがありません'}
                </strong>
                <p>
                  {upcoming.length === 0
                    ? '関心を伝えると、エージェントが申込締切と開催日を分けて探します。'
                    : '絞り込みを解除すると他のイベントを確認できます。'}
                </p>
                {upcoming.length === 0 ? (
                  <button
                    type="button"
                    className="primary-button"
                    onClick={() => navigate('/agent')}
                  >
                    関心を伝えて探索
                  </button>
                ) : (
                  <button type="button" className="ghost-button" onClick={() => setFilter('all')}>
                    絞り込みを解除
                  </button>
                )}
              </div>
            ) : (
              <div className="list">
                {visible.map((event) => (
                  <EventCard
                    key={event.eventId}
                    event={event}
                    saved={Boolean(saved[event.eventId])}
                    calendar={calendar[event.eventId]}
                    onToggleSaved={toggleSaved}
                    onOpenCalendar={setSheetEvent}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <CalendarSheet
        event={sheetEvent}
        onClose={() => setSheetEvent(null)}
        onConfirm={register}
      />
    </>
  )
}
