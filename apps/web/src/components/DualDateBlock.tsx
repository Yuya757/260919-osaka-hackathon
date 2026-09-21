/**
 * 申込締切と開催日を縦2段で示す（画面設計書 §3.3 / 上位§5-1）。
 *
 * 混同を防ぐのがこの部品の唯一の役目なので、区別は色だけに依存させない。
 * 位置（上/下）・ノード形状（円/四角）・アイコン・ラベル文字・文字ウェイトの
 * 5軸で差をつけ、グレースケールでも読み分けられるようにする。
 */
import type { Event } from '../types/api'
import { deadlineLabel, gapDays, heldLabel, relativeLabel } from '../lib/eventView'

type Props = {
  event: Event
  /** 詳細画面ではひとまわり大きく出す */
  size?: 'card' | 'detail'
}

export function DualDateBlock({ event, size = 'card' }: Props) {
  const tz = event.dates.timezone
  const deadlineUnknown = !event.dates.applicationDeadline
  const gap = gapDays(event)

  return (
    <div className={`rail rail-${size}`}>
      <div className={`rail-row rail-deadline${deadlineUnknown ? ' is-unknown' : ''}`}>
        <span className="rail-node" aria-hidden="true" />
        <span className="rail-icon" aria-hidden="true">
          🚨
        </span>
        <span className="rail-label">申込締切</span>
        <span className="rail-value">{deadlineLabel(event)}</span>
        <span className="rail-rel">
          {relativeLabel(event.dates.applicationDeadline, 'left', tz)}
        </span>
      </div>

      <div className="rail-gap">
        <i aria-hidden="true" />
        <span>
          {gap === null ? '締切が未確認のため間隔を出せません' : `この間に ${gap} 日`}
        </span>
      </div>

      <div className="rail-row rail-held">
        <span className="rail-node" aria-hidden="true" />
        <span className="rail-icon" aria-hidden="true">
          📅
        </span>
        <span className="rail-label">開催日</span>
        <span className="rail-value">{heldLabel(event)}</span>
        <span className="rail-rel">{relativeLabel(event.dates.eventStart, 'after', tz)}</span>
      </div>
    </div>
  )
}
