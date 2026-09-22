/**
 * S-03 カレンダー（2軸月表示）
 *
 * 申込締切は「右上の点」、開催日は「下端の帯」として、位置と形で区別する。
 * 帯は複数日開催が横に連続するので、点との性質の違いが色を見なくても伝わる。
 * 月の予定は下に日付順で並べ、押すと詳細へ移る。
 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { dayDate, dayKey } from '../lib/eventView'
import type { Event } from '../types/api'

const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土']

type AgendaItem = {
  key: string
  date: Date
  kind: 'deadline' | 'held'
  event: Event
}

function localKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`
}

export function CalendarScreen() {
  const { events, posts } = useAppState()
  const navigate = useNavigate()
  const today = new Date()
  const todayKey = localKey(today)
  const [cursor, setCursor] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1))

  // 主催者投稿のイベントも載せる。AI 収集分と結び付いた投稿は相手側が既に載っている
  const shown = useMemo(
    () => [
      ...events,
      ...posts.filter((post) => !post.linkedEventId).map((post) => post.event),
    ],
    [events, posts],
  )

  const { deadlineIndex, heldIndex, agenda } = useMemo(() => {
    const deadlines = new Set<string>()
    const held = new Map<string, { first: boolean; last: boolean }>()
    const items: AgendaItem[] = []

    for (const event of shown) {
      const tz = event.dates.timezone
      // 締切が不明なイベントは締切マーカーを描かない。推測しない（§3.2）
      if (event.dates.applicationDeadline) {
        const date = dayDate(event.dates.applicationDeadline, tz)
        deadlines.add(dayKey(event.dates.applicationDeadline, tz))
        items.push({ key: `${event.eventId}-deadline`, date, kind: 'deadline', event })
      }
      const start = dayDate(event.dates.eventStart, tz)
      const end = event.dates.eventEnd ? dayDate(event.dates.eventEnd, tz) : start
      items.push({ key: `${event.eventId}-held`, date: start, kind: 'held', event })
      for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const key = localKey(d)
        const current = held.get(key)
        const mark = { first: key === localKey(start), last: key === localKey(end) }
        // 同じ日に複数の開催が重なるときは、帯の端を丸めない側を優先する
        held.set(
          key,
          current ? { first: current.first && mark.first, last: current.last && mark.last } : mark,
        )
      }
    }
    items.sort((a, b) => a.date.getTime() - b.date.getTime() || (a.kind === 'deadline' ? -1 : 1))
    return { deadlineIndex: deadlines, heldIndex: held, agenda: items }
  }, [shown])

  const cells = useMemo(() => {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
    const start = new Date(first.getFullYear(), first.getMonth(), 1 - first.getDay())
    const daysInMonth = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0).getDate()
    const rows = Math.ceil((first.getDay() + daysInMonth) / 7)
    return Array.from({ length: rows * 7 }, (_, i) => {
      const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
      return { date, key: localKey(date), outside: date.getMonth() !== cursor.getMonth() }
    })
  }, [cursor])

  const monthAgenda = useMemo(
    () =>
      agenda.filter(
        (item) =>
          item.date.getFullYear() === cursor.getFullYear() &&
          item.date.getMonth() === cursor.getMonth(),
      ),
    [agenda, cursor],
  )

  const shiftMonth = (delta: number) =>
    setCursor((c) => new Date(c.getFullYear(), c.getMonth() + delta, 1))

  return (
    <div className="calendar">
      <div className="month-nav">
        <h1>
          {cursor.getFullYear()}年{cursor.getMonth() + 1}月
        </h1>
        <button type="button" className="icon-button" onClick={() => shiftMonth(-1)} aria-label="前の月">
          ‹
        </button>
        <button type="button" className="icon-button" onClick={() => shiftMonth(1)} aria-label="次の月">
          ›
        </button>
      </div>

      <div className="weekdays" aria-hidden="true">
        {WEEKDAYS.map((w) => (
          <span key={w}>{w}</span>
        ))}
      </div>

      <div className="month-grid">
        {cells.map(({ date, key, outside }) => {
          const hasDeadline = !outside && deadlineIndex.has(key)
          const held = outside ? undefined : heldIndex.get(key)
          const label =
            `${date.getMonth() + 1}月${date.getDate()}日` +
            (hasDeadline ? ' 申込締切あり' : '') +
            (held ? ' 開催あり' : '')
          return (
            <div
              key={key}
              className={`day${outside ? ' is-outside' : ''}${key === todayKey ? ' is-today' : ''}`}
              aria-label={outside ? undefined : label}
            >
              {outside ? '' : date.getDate()}
              {hasDeadline && <span className="mark-deadline" aria-hidden="true" />}
              {held && (
                <span
                  className={`mark-held${held.first ? ' is-start' : ''}${held.last ? ' is-end' : ''}`}
                  aria-hidden="true"
                />
              )}
            </div>
          )
        })}
      </div>

      <div className="legend">
        <span>
          <i className="dot dot-deadline" aria-hidden="true" />
          申込締切
        </span>
        <span>
          <i className="bar-held" aria-hidden="true" />
          開催日
        </span>
      </div>

      <div className="agenda">
        {monthAgenda.length === 0 && <p className="empty">この月に予定はありません。</p>}
        {monthAgenda.map((item) => (
          <button
            key={item.key}
            type="button"
            className="agenda-row"
            onClick={() => navigate(`/events/${encodeURIComponent(item.event.eventId)}`)}
          >
            <span className="agenda-date">
              {item.date.getMonth() + 1}/{item.date.getDate()}
            </span>
            <span
              className={`dot ${item.kind === 'deadline' ? 'dot-deadline' : 'dot-held'}`}
              aria-hidden="true"
            />
            <span className="agenda-title">{item.event.title}</span>
            <span className="agenda-kind">{item.kind === 'deadline' ? '締切' : '開催'}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
