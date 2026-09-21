/** 一覧のイベントカード（画面設計書 S-01）。 */
import { useNavigate } from 'react-router-dom'
import type { Event, GoogleCalendarEventIds } from '../types/api'
import { categoryLabel, formatLocationType, placeLabel } from '../lib/eventView'
import { CalendarBadge, UrgentBadge, ValidationBadge } from './Badges'
import { DualDateBlock } from './DualDateBlock'
import { CalendarIcon, HeartIcon } from './Icon'

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

  return (
    <article className={`event-card${partial ? ' is-partial' : ''}`}>
      <div className="event-card-top">
        <div className="chip-row">
          <span className="chip chip-category">{categoryLabel(event.category)}</span>
          <UrgentBadge event={event} />
          {partial && <ValidationBadge status={event.validationStatus} />}
        </div>
        <button
          type="button"
          className="icon-button bookmark"
          aria-pressed={saved}
          aria-label={saved ? `${event.title}の保存を解除` : `${event.title}を保存`}
          onClick={() => onToggleSaved(event.eventId)}
        >
          <HeartIcon filled={saved} />
        </button>
      </div>

      <button
        type="button"
        className="event-card-main"
        onClick={() => navigate(`/events/${encodeURIComponent(event.eventId)}`)}
      >
        <h3 className="event-title">{event.title}</h3>
        <p className="event-meta">
          {event.organizer || '主催者未確認'} · {placeLabel(event)} ·{' '}
          {formatLocationType(event.location.type)}
        </p>
        <DualDateBlock event={event} />
      </button>

      <div className="event-card-foot">
        {event.recommendation && (
          <span className="match-score">適合 {event.recommendation.score}%</span>
        )}
        <CalendarBadge ids={calendar} />
        <span className="spacer" />
        <button type="button" className="primary-button" onClick={() => onOpenCalendar(event)}>
          <CalendarIcon />
          {calendar ? '登録内容を変更' : 'カレンダーに登録'}
        </button>
      </div>
    </article>
  )
}
