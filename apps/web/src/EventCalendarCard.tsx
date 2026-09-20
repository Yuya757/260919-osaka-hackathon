import { useId, useState } from 'react'
import './EventCalendarCard.css'

export type EventCalendarCardEvent = {
  id: string
  title: string
  organizer: string
  category: string
  location: string
  format: '会場' | 'オンライン' | 'ハイブリッド'
  deadline: string
  eventDate: string
  description: string
  match: number
  source: string
  urgent?: boolean
}

type CalendarTarget = 'deadline' | 'event' | 'both'
type Registration = { deadline: boolean; event: boolean }

/** UI確認用。登録状態はメモリ内だけで管理し、外部カレンダーへは書き込まない。 */
export function EventCalendarCard({ event }: { event: EventCalendarCardEvent }) {
  // 表示対象が変わった場合に、別イベントの登録状態を引き継がない。
  return <EventCalendarCardContent key={event.id} event={event} />
}

function EventCalendarCardContent({ event }: { event: EventCalendarCardEvent }) {
  const titleId = useId()
  const [registration, setRegistration] = useState<Registration>({
    deadline: false,
    event: false,
  })
  const [message, setMessage] = useState('')
  const bothRegistered = registration.deadline && registration.event
  const hasRegistration = registration.deadline || registration.event
  const onlineOnly = event.format === 'オンライン'
  const status = bothRegistered
    ? 'カレンダー登録済み'
    : registration.deadline
      ? 'カレンダー登録済み（申込締切のみ）'
      : registration.event
        ? 'カレンダー登録済み（本番日程のみ）'
        : '未登録'

  function register(target: CalendarTarget) {
    setRegistration(current => ({
      deadline: current.deadline || target === 'deadline' || target === 'both',
      event: current.event || target === 'event' || target === 'both',
    }))
    setMessage('')
  }

  function resetRegistration() {
    setRegistration({ deadline: false, event: false })
    setMessage('未登録に戻しました。')
  }

  return (
    <article className={`calendar-card${event.urgent ? ' calendar-card--urgent' : ''}`} aria-labelledby={titleId}>
      <div className="calendar-card__score">
        <strong>{event.match}%</strong><small>関心に一致</small>
      </div>
      <div className="calendar-card__body">
        <div className="calendar-card__tags">
          <span>{event.category}</span>
          {event.urgent && <span className="calendar-card__badge calendar-card__badge--urgent">締切間近</span>}
        </div>
        <h3 id={titleId} className="calendar-card__title">{event.title}</h3>
        <div className="calendar-card__venue-row">
          <p className="calendar-card__venue">
            <span>{onlineOnly ? '参加方法' : '会場'}</span>
            <strong>{event.location}</strong>
          </p>
          {!onlineOnly && (
            <div className="calendar-card__travel" aria-label="現在地から会場への経路情報">
              <span className="calendar-card__travel-label">現在地 → 会場</span>
              <div className="calendar-card__travel-values">
                <span>距離：未取得</span><span>時間：未取得</span>
              </div>
              <button className="calendar-card__route" type="button" disabled>駅すぱあとで経路を見る</button>
            </div>
          )}
        </div>
        {!onlineOnly && <p className="calendar-card__note">経路情報は駅すぱあと連携後に表示予定です。現在地は取得していません。</p>}
        <p className="calendar-card__note">{event.organizer}</p>
        <p className="calendar-card__note">{event.description}</p>
        <div className="calendar-card__dates">
          <div className="calendar-card__date calendar-card__date--deadline">
            <span>申込締切</span><strong>{event.deadline}</strong>
          </div>
          <div className="calendar-card__date calendar-card__date--event">
            <span>本番日程</span><strong>{event.eventDate}</strong>
          </div>
        </div>
        <div className="calendar-card__source">{event.source}</div>
        <p className="calendar-card__status" role="status" aria-atomic="true">
          <span className={`calendar-card__badge${hasRegistration ? ' calendar-card__badge--saved' : ''}`}>{status}</span>
        </p>
        <div className="calendar-card__actions" role="group" aria-label={`${event.title}のカレンダー登録（デモ）`}>
          <button type="button" disabled={registration.deadline} onClick={() => register('deadline')}>
            {registration.deadline ? '申込締切は登録済み' : '申込締切を登録'}
          </button>
          <button type="button" disabled={registration.event} onClick={() => register('event')}>
            {registration.event ? '本番日程は登録済み' : '本番日程を登録'}
          </button>
          <button className="calendar-card__register-both" type="button" disabled={bothRegistered} onClick={() => register('both')}>
            {bothRegistered ? '両方とも登録済み' : '両方まとめて登録'}
          </button>
          <button className="calendar-card__reset" type="button" onClick={resetRegistration}>未登録に戻して試す</button>
        </div>
        <p className="calendar-card__message" role="status">{message}</p>
        <p className="calendar-card__demo">デモ表示です。実際のカレンダーには登録されません。</p>
      </div>
    </article>
  )
}
