/** 一覧の1行（画面設計書 S-01）。カードではなく罫線で区切る。 */
import { useNavigate } from 'react-router-dom'
import type { Event, GoogleCalendarEventIds } from '../types/api'
import { formatLocationType, isCalendarRegistered, placeLabel } from '../lib/eventView'
import { DualDateBlock } from './DualDateBlock'

type Props = {
  event: Event
  saved: boolean
  calendar?: GoogleCalendarEventIds
  onToggleSaved: (eventId: string) => void
  onOpenCalendar: (event: Event) => void
}

export function EventCard({ event, saved, calendar, onToggleSaved, onOpenCalendar }: Props) {
  const navigate = useNavigate()
  const partial = event.validationStatus === 'partial'
  const registered = isCalendarRegistered(calendar)

  return (
    <article className="row">
      <div className="row-main">
        <div className="row-title">
          <button
            type="button"
            className="row-title-button"
            onClick={() => navigate(`/events/${encodeURIComponent(event.eventId)}`)}
          >
            {event.title}
          </button>
          {partial && <span className="tag">要確認</span>}
        </div>
        <p className="row-meta">
          {event.organizer || '主催者未確認'} · {placeLabel(event)} ·{' '}
          {formatLocationType(event.location.type)}
        </p>
        <DualDateBlock event={event} />
      </div>

      <div className="row-side">
        {event.recommendation ? (
          <span className="row-score">適合 {event.recommendation.score}</span>
        ) : (
          <span className="row-score" aria-hidden="true" />
        )}
        <div className="row-actions">
          <button
            type="button"
            className={`chip-button${saved ? ' is-on' : ''}`}
            aria-pressed={saved}
            aria-label={saved ? `${event.title}の保存を解除` : `${event.title}を保存`}
            onClick={() => onToggleSaved(event.eventId)}
          >
            {saved ? '保存済' : '保存'}
          </button>
          <button
            type="button"
            className={`chip-button${registered ? ' is-on' : ''}`}
            aria-label={
              registered
                ? `${event.title}のカレンダー登録内容を変更`
                : `${event.title}をカレンダーに登録`
            }
            onClick={() => onOpenCalendar(event)}
          >
            {registered ? '登録済' : '登録'}
          </button>
        </div>
      </div>
    </article>
  )
}
