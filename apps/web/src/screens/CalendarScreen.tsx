/**
 * S-03 カレンダー（2軸月表示）
 *
 * 360px幅では1セル約47pxしかないため、2軸をテキストで並べられない。
 * 申込締切は「右上の点」、開催日は「下端の帯」として、位置と形で区別する。
 * 帯は複数日開催が横に連続するので、点との性質の違いが色を見なくても伝わる。
 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { dayDate, dayKey, formatTime } from '../lib/eventView'
import { RunProgressBanner } from '../components/RunProgressBanner'
import type { Event } from '../types/api'

const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土']
type Axis = 'both' | 'deadline' | 'held'

function localKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`
}

export function CalendarScreen() {
  const { events } = useAppState()
  const navigate = useNavigate()
  const today = new Date()
  const [cursor, setCursor] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1))
  const [selected, setSelected] = useState(() => localKey(today))
  const [axis, setAxis] = useState<Axis>('both')

  const { deadlineIndex, heldIndex, unknownDeadline } = useMemo(() => {
    const deadlines = new Map<string, Event[]>()
    const held = new Map<string, { event: Event; first: boolean; last: boolean }[]>()
    const unknown: Event[] = []

    for (const event of events) {
      const tz = event.dates.timezone
      // 締切が不明なイベントは締切マーカーを描かない。推測しない（§3.2）
      if (event.dates.applicationDeadline) {
        const key = dayKey(event.dates.applicationDeadline, tz)
        deadlines.set(key, [...(deadlines.get(key) ?? []), event])
      } else {
        unknown.push(event)
      }
      const start = dayDate(event.dates.eventStart, tz)
      const end = event.dates.eventEnd ? dayDate(event.dates.eventEnd, tz) : start
      const startKey = localKey(start)
      const endKey = localKey(end)
      for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const key = localKey(d)
        held.set(key, [
          ...(held.get(key) ?? []),
          { event, first: key === startKey, last: key === endKey },
        ])
      }
    }
    return { deadlineIndex: deadlines, heldIndex: held, unknownDeadline: unknown }
  }, [events])

  const cells = useMemo(() => {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
    const start = new Date(first.getFullYear(), first.getMonth(), 1 - first.getDay())
    return Array.from({ length: 42 }, (_, i) => {
      const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
      return { date, key: localKey(date), outside: date.getMonth() !== cursor.getMonth() }
    })
  }, [cursor])

  const selectedDate = useMemo(() => {
    const [y, m, d] = selected.split('-').map(Number)
    return new Date(y, m - 1, d)
  }, [selected])

  const dayDeadlines = deadlineIndex.get(selected) ?? []
  const dayHeld = heldIndex.get(selected) ?? []
  const monthLabel = `${cursor.getFullYear()}年${cursor.getMonth() + 1}月`
  /**
   * 月を送ったら選択日もその月へ移す。移さないと、10月のグリッドを見ながら
   * 下のリストだけ9月の日付、という状態になって読み手が混乱する。
   * 送った先が今月なら今日を、そうでなければ1日を選ぶ。
   */
  const shiftMonth = (delta: number) => {
    setCursor((c) => {
      const next = new Date(c.getFullYear(), c.getMonth() + delta, 1)
      const now = new Date()
      const isThisMonth =
        next.getFullYear() === now.getFullYear() && next.getMonth() === now.getMonth()
      setSelected(localKey(isThisMonth ? now : next))
      return next
    })
  }

  return (
    <>
      <header className="app-header">
        <div className="header-main">
          <h1 className="header-compact">カレンダー</h1>
        </div>
        <button
          type="button"
          className="ghost-button"
          onClick={() => {
            const now = new Date()
            setCursor(new Date(now.getFullYear(), now.getMonth(), 1))
            setSelected(localKey(now))
          }}
        >
          今日
        </button>
      </header>

      <RunProgressBanner />

      <div className="scroll-area">
        <div className="month-nav">
          <button type="button" className="icon-button" onClick={() => shiftMonth(-1)} aria-label="前の月">
            ‹
          </button>
          <strong>{monthLabel}</strong>
          <button type="button" className="icon-button" onClick={() => shiftMonth(1)} aria-label="次の月">
            ›
          </button>
        </div>

        <div className="segmented" role="group" aria-label="表示する軸">
          {(
            [
              ['both', '両方'],
              ['deadline', '締切のみ'],
              ['held', '開催のみ'],
            ] as [Axis, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={axis === value}
              onClick={() => setAxis(value)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="weekday-row" aria-hidden="true">
          {WEEKDAYS.map((w) => (
            <span key={w}>{w}</span>
          ))}
        </div>

        <div className="month-grid">
          {cells.map(({ date, key, outside }) => {
            const deadlines = axis === 'held' ? [] : deadlineIndex.get(key) ?? []
            const held = axis === 'deadline' ? [] : heldIndex.get(key) ?? []
            const label =
              `${date.getMonth() + 1}月${date.getDate()}日` +
              (deadlines.length ? ` 申込締切${deadlines.length}件` : '') +
              (held.length ? ` 開催${held.length}件` : '')
            return (
              <button
                key={key}
                type="button"
                className={`day-cell${outside ? ' is-outside' : ''}`}
                aria-pressed={selected === key}
                aria-label={label}
                onClick={() => setSelected(key)}
              >
                <span className="day-number">{date.getDate()}</span>
                {key === localKey(today) && <span className="today-dot" aria-hidden="true" />}
                {deadlines.length > 0 && <span className="mark-deadline" aria-hidden="true" />}
                {held.length > 0 && (
                  <span
                    className={`mark-held${held[0].first ? ' is-start' : ''}${
                      held[0].last ? ' is-end' : ''
                    }`}
                    aria-hidden="true"
                  />
                )}
              </button>
            )
          })}
        </div>

        <div className="legend">
          <span>
            <i className="key-deadline" aria-hidden="true" />
            申込締切（点）
          </span>
          <span>
            <i className="key-held" aria-hidden="true" />
            開催日（帯）
          </span>
        </div>

        <section className="agenda">
          <h2>
            {selectedDate.getMonth() + 1}月{selectedDate.getDate()}日（
            {WEEKDAYS[selectedDate.getDay()]}）
          </h2>

          {dayDeadlines.length === 0 && dayHeld.length === 0 && (
            <p className="event-meta">この日に予定はありません。</p>
          )}

          {dayDeadlines.length > 0 && (
            <div className="agenda-group">
              <p className="agenda-label">申込締切（{dayDeadlines.length}）</p>
              {dayDeadlines.map((event) => (
                <button
                  key={event.eventId}
                  type="button"
                  className="agenda-row is-deadline"
                  onClick={() => navigate(`/events/${encodeURIComponent(event.eventId)}`)}
                >
                  <span aria-hidden="true">🚨</span>
                  <span className="agenda-title">{event.title}</span>
                  <span className="agenda-time">
                    {event.dates.applicationDeadlinePrecision === 'date'
                      ? '時刻未確認'
                      : formatTime(event.dates.applicationDeadline!, event.dates.timezone)}
                  </span>
                </button>
              ))}
            </div>
          )}

          {dayHeld.length > 0 && (
            <div className="agenda-group">
              <p className="agenda-label">開催（{dayHeld.length}）</p>
              {dayHeld.map(({ event }) => (
                <button
                  key={event.eventId}
                  type="button"
                  className="agenda-row is-held"
                  onClick={() => navigate(`/events/${encodeURIComponent(event.eventId)}`)}
                >
                  <span aria-hidden="true">📅</span>
                  <span className="agenda-title">{event.title}</span>
                  <span className="agenda-time">
                    {formatTime(event.dates.eventStart, event.dates.timezone)}
                  </span>
                </button>
              ))}
            </div>
          )}

          {unknownDeadline.length > 0 && (
            <div className="agenda-group">
              {/* 締切が不明なイベントを黙って落とさない */}
              <p className="agenda-label">締切未確認（{unknownDeadline.length}）</p>
              {unknownDeadline.map((event) => (
                <button
                  key={event.eventId}
                  type="button"
                  className="agenda-row is-unknown"
                  onClick={() => navigate(`/events/${encodeURIComponent(event.eventId)}`)}
                >
                  <span aria-hidden="true">○</span>
                  <span className="agenda-title">{event.title}</span>
                  <span className="agenda-time">—</span>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  )
}
