/**
 * 一覧の行に出す根拠（出典と引用）。普段は「根拠」の小さな印だけを出し、
 * カーソルを合わせる（スマホでは押す）と出典と引用を浮かせて見せる。全文は詳細で。
 */
import { useId, useState } from 'react'
import type { EvidencePreview } from '../types/api'
import { hostOf } from '../lib/eventView'

function fieldLabel(item: EvidencePreview): string {
  if (item.supports.includes('dates.applicationDeadline')) return '締切の根拠'
  if (item.supports.includes('dates.eventStart')) return '開催日の根拠'
  return '根拠'
}

export function EvidenceTip({ items }: { items: EvidencePreview[] }) {
  const id = useId()
  // タッチ端末にはホバーが無いので、押して開け閉めもできるようにする
  const [pinned, setPinned] = useState(false)
  return (
    <span
      className={`evidence-tip${pinned ? ' is-open' : ''}`}
      onMouseLeave={() => setPinned(false)}
    >
      <button
        type="button"
        className="evidence-tip-trigger"
        aria-describedby={id}
        aria-expanded={pinned}
        onClick={() => setPinned((open) => !open)}
      >
        根拠 {items.length}件
      </button>
      <span className="evidence-tip-body" role="tooltip" id={id}>
        {items.map((item) => (
          <span className="evidence-tip-item" key={`${item.sourceUrl}-${item.excerpt}`}>
            <span className="evidence-tip-field">{fieldLabel(item)}</span>
            <a href={item.sourceUrl} target="_blank" rel="noopener noreferrer">
              {hostOf(item.sourceUrl)}
            </a>
            <span className="evidence-tip-quote">「{item.excerpt}」</span>
          </span>
        ))}
      </span>
    </span>
  )
}
