/**
 * 申込締切と開催日を縦2段で示す（画面設計書 §3.3 / 上位§5-1）。
 *
 * 混同を防ぐのがこの部品の唯一の役目なので、区別は色だけに依存させない。
 * 上段は丸いノード、下段は四角いノードにし、ラベル文字も添える。
 * 締切が近いときだけ上段を赤にする。締切が未確認のときはノードを薄くする。
 */
import type { Event } from '../types/api'
import {
  deadlineLabel,
  formatDate,
  gapDays,
  heldLabel,
  heldMilestone,
  heldRowLabel,
  isUrgent,
  relativeLabel,
} from '../lib/eventView'

type Props = {
  event: Event
  /** 詳細画面ではひとまわり大きく出し、間隔の行も添える */
  size?: 'card' | 'detail'
}

export function DualDateBlock({ event, size = 'card' }: Props) {
  const tz = event.dates.timezone
  const unknown = !event.dates.applicationDeadline
  const urgent = isUrgent(event)
  const gap = gapDays(event)
  const named = heldMilestone(event)
  const milestones = (event.dates.milestones ?? []).filter((m) => m !== named)

  return (
    <div className={`dates dates-${size}`}>
      <div className={`dates-row is-deadline${unknown ? ' is-unknown' : ''}${urgent ? ' is-urgent' : ''}`}>
        <span className="dates-node" aria-hidden="true" />
        <span className="dates-label">申込締切</span>
        <span className="dates-value">{deadlineLabel(event)}</span>
        <span className="dates-rel">{relativeLabel(event.dates.applicationDeadline, 'left', tz)}</span>
      </div>
      <div className="dates-row is-held">
        <span className="dates-node" aria-hidden="true" />
        <span className="dates-label">{heldRowLabel(event)}</span>
        <span className="dates-value">{heldLabel(event)}</span>
        <span className="dates-rel">
          {event.dates.eventStart ? relativeLabel(event.dates.eventStart, 'after', tz) : ''}
        </span>
      </div>
      {/* 節目（一次選考通過・最終審査会・結果発表など）。詳細だけに出す */}
      {size === 'detail' &&
        milestones.map((milestone) => (
          <div className="dates-row is-milestone" key={`${milestone.label}-${milestone.at}`}>
            <span className="dates-node" aria-hidden="true" />
            <span className="dates-label">{milestone.label}</span>
            <span className="dates-value">{formatDate(milestone.at, tz)}</span>
          </div>
        ))}
      {size === 'detail' && (
        <p className="dates-gap">
          {gap === null
            ? '締切が未確認のため間隔を出せません'
            : `締切から${named?.label ?? (event.kind === 'hackathon' ? '開催' : '実施')}まで ${gap} 日`}
        </p>
      )}
    </div>
  )
}
