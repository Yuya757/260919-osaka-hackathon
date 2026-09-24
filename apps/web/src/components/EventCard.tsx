/** 一覧の1行（画面設計書 S-01）。カードではなく罫線で区切る。 */
import { useNavigate } from 'react-router-dom'
import type { Event, GoogleCalendarEventIds } from '../types/api'
import {
  formatLocationType,
  hostOf,
  isCalendarRegistered,
  kindLabel,
  needsCheck,
  placeLabel,
} from '../lib/eventView'
import { DualDateBlock } from './DualDateBlock'
import { ScoreRing } from './ScoreRing'

type Props = {
  event: Event
  saved: boolean
  calendar?: GoogleCalendarEventIds
  onToggleSaved: (eventId: string) => void
  onOpenCalendar: (event: Event) => void
}

export function EventCard({ event, saved, calendar, onToggleSaved, onOpenCalendar }: Props) {
  const navigate = useNavigate()
  const partial = needsCheck(event)
  const registered = isCalendarRegistered(calendar)

  return (
    <article
      className={`row${event.recommendation ? ' has-score' : ''}${event.organizerEdit ? ' is-verified' : ''}`}
    >
      <div className="row-main">
        <div className="row-title">
          <button
            type="button"
            className="row-title-button"
            onClick={() => navigate(`/events/${encodeURIComponent(event.eventId)}`)}
          >
            {event.title}
          </button>
          {/* 既定はハッカソン。混ざったときだけ種別を出す */}
          {event.kind !== 'hackathon' && <span className="tag">{kindLabel(event.kind)}</span>}
          {event.organizerEdit && <span className="tag tag-verified">✓ 主催者確認済み</span>}
          {partial && <span className="tag">要確認</span>}
        </div>
        <p className="row-meta">
          {event.organizer || '主催者未確認'} · {placeLabel(event)} ·{' '}
          {formatLocationType(event.location.type)}
        </p>
        <DualDateBlock event={event} />
        {event.recommendation?.reason && (
          <p className="row-reason">{event.recommendation.reason}</p>
        )}
        {/* 根拠（出典と引用）。締切 → 開催日の順で最大2件。全文は詳細で */}
        {(event.evidencePreview ?? []).slice(0, 2).map((item) => (
          <p className="row-evidence" key={`${item.sourceUrl}-${item.excerpt}`}>
            <span className="row-evidence-field">
              {item.supports.includes('dates.applicationDeadline')
                ? '締切の根拠'
                : item.supports.includes('dates.eventStart')
                  ? '開催日の根拠'
                  : '根拠'}
            </span>
            <a href={item.sourceUrl} target="_blank" rel="noopener noreferrer">
              {hostOf(item.sourceUrl)}
            </a>
            <span className="row-evidence-quote">「{item.excerpt}」</span>
          </p>
        ))}
      </div>

      {event.recommendation && <ScoreRing score={event.recommendation.score} />}

      <div className="row-side">
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
