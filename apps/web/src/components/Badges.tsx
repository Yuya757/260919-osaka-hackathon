/** ステータスバッジ（画面設計書 §3.1 / §3.4）。 */
import type { Event, ValidationStatus } from '../types/api'
import { isCalendarRegistered, isUrgent, validationLabel } from '../lib/eventView'
import type { GoogleCalendarEventIds } from '../types/api'

export function ValidationBadge({ status }: { status: ValidationStatus }) {
  // quarantined / rejected は通常UIに出さないので、ここには来ない想定
  const partial = status === 'partial'
  return (
    <span className={partial ? 'badge badge-partial' : 'badge badge-verified'}>
      {partial ? '要確認' : `✓ ${validationLabel(status)}`}
    </span>
  )
}

export function UrgentBadge({ event }: { event: Event }) {
  if (!isUrgent(event)) return null
  return <span className="badge badge-urgent">締切間近</span>
}

export function CalendarBadge({ ids }: { ids?: GoogleCalendarEventIds }) {
  if (!isCalendarRegistered(ids)) {
    return <span className="badge badge-plain">未登録</span>
  }
  const both = ids?.deadlineEventId && ids?.mainEventId
  const label = both ? 'カレンダー登録済み' : ids?.deadlineEventId ? '締切のみ登録済み' : '本番のみ登録済み'
  return <span className="badge badge-calendar">✓ {label}</span>
}
