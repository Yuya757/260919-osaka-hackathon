/** S-04 保存済み */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { daysUntil, isFinished } from '../lib/eventView'
import { EventCard } from '../components/EventCard'
import { CalendarSheet } from '../components/CalendarSheet'
import { RunProgressBanner } from '../components/RunProgressBanner'
import type { Event } from '../types/api'

export function SavedScreen() {
  const { events, saved, calendar, toggleSaved, register } = useAppState()
  const [sheetEvent, setSheetEvent] = useState<Event | null>(null)
  const navigate = useNavigate()

  const { open, unknown, finished } = useMemo(() => {
    const all = events.filter((event) => saved[event.eventId])
    return {
      // 締切が近い順。締切が不明なものは混ぜず別セクションにする
      open: all
        .filter((e) => !isFinished(e) && e.dates.applicationDeadline)
        .sort(
          (a, b) =>
            (daysUntil(a.dates.applicationDeadline, a.dates.timezone) ?? 0) -
            (daysUntil(b.dates.applicationDeadline, b.dates.timezone) ?? 0),
        ),
      unknown: all.filter((e) => !isFinished(e) && !e.dates.applicationDeadline),
      finished: all.filter(isFinished),
    }
  }, [events, saved])

  const total = open.length + unknown.length + finished.length

  const renderCard = (event: Event) => (
    <EventCard
      key={event.eventId}
      event={event}
      saved
      calendar={calendar[event.eventId]}
      onToggleSaved={toggleSaved}
      onOpenCalendar={setSheetEvent}
    />
  )

  return (
    <>
      <header className="app-header">
        <div className="header-main">
          <h1 className="header-compact">保存済み</h1>
          <p className="header-eyebrow">{total}件</p>
        </div>
      </header>

      <RunProgressBanner />

      <div className="scroll-area">
        {total === 0 ? (
          <div className="empty">
            <strong>保存したイベントはありません</strong>
            <p>一覧の♡で保存すると、ここに申込締切が近い順で並びます。</p>
            <button type="button" className="primary-button" onClick={() => navigate('/')}>
              イベントを見る
            </button>
          </div>
        ) : (
          <>
            {open.length > 0 && (
              <>
                <p className="count-row">申込受付中（{open.length}）</p>
                <div className="list">{open.map(renderCard)}</div>
              </>
            )}
            {unknown.length > 0 && (
              <>
                <p className="count-row">締切未確認（{unknown.length}）</p>
                <div className="list">{unknown.map(renderCard)}</div>
              </>
            )}
            <details className="closed-section">
              <summary>終了（{finished.length}）</summary>
              {finished.length > 0 ? (
                <div className="list">{finished.map(renderCard)}</div>
              ) : (
                <p className="event-meta">終了したイベントはありません。</p>
              )}
            </details>
          </>
        )}
      </div>

      <CalendarSheet event={sheetEvent} onClose={() => setSheetEvent(null)} onConfirm={register} />
    </>
  )
}
