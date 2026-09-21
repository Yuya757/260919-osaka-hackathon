/**
 * 根拠シート（画面設計書 S-08 / §7.2）。
 *
 * 外部ページ由来の文字列は信頼できないデータとして扱い、HTMLとして解釈せず
 * テキストで出す（§10.1）。全文は保持しないので抜粋のみを表示する。
 */
import { useEffect, useState } from 'react'
import { listEvidence } from '../api/client'
import type { Evidence } from '../types/api'
import { hostOf } from '../lib/eventView'
import { BottomSheet } from './BottomSheet'
import { ExternalIcon } from './Icon'

const SOURCE_LABEL: Record<Evidence['sourceType'], string> = {
  official: '公式',
  organizer: '主催者',
  aggregator: '集約サイト',
  other: 'その他',
}

const FIELD_LABEL: Record<string, string> = {
  title: 'イベント名',
  summary: '概要',
  organizer: '主催者',
  category: 'カテゴリ',
  location: '開催場所',
  'dates.eventStart': '開催日',
  'dates.eventEnd': '終了日',
  'dates.applicationDeadline': '申込締切',
  officialUrl: '公式URL',
  applicationUrl: '申込URL',
}

type Props = { eventId: string | null; onClose: () => void }

export function EvidenceSheet({ eventId, onClose }: Props) {
  const [items, setItems] = useState<Evidence[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!eventId) return
    let cancelled = false
    setItems(null)
    setError(null)
    listEvidence(eventId)
      .then((result) => {
        if (!cancelled) setItems(result.evidence)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : '根拠を取得できませんでした。')
        }
      })
    return () => {
      cancelled = true
    }
  }, [eventId])

  if (!eventId) return null

  return (
    <BottomSheet open onClose={onClose} label="この情報の根拠">
      <h2 className="sheet-title">この情報の根拠</h2>
      <p className="sheet-sub">表示している日程が何を出典としているかを確認できます。</p>

      {error && <p className="sheet-error">{error}</p>}
      {!items && !error && <p className="sheet-note">読み込んでいます…</p>}
      {items && items.length === 0 && (
        <p className="sheet-note">根拠を取得できませんでした。公式サイトでご確認ください。</p>
      )}

      {items?.map((item) => (
        <article className="evidence" key={item.evidenceId}>
          <div className="evidence-head">
            <span className={`chip chip-source source-${item.sourceType}`}>
              {SOURCE_LABEL[item.sourceType]}
            </span>
            <span className="evidence-host">{hostOf(item.canonicalUrl || item.sourceUrl)}</span>
          </div>
          {item.title && <p className="evidence-title">{item.title}</p>}
          {item.excerpt && (
            <blockquote className="evidence-quote">
              <span className="sr-only">引用: </span>
              {item.excerpt}
            </blockquote>
          )}
          <div className="chip-row">
            {item.supports.map((field) => (
              <span className="chip" key={field}>
                {FIELD_LABEL[field] ?? field}
              </span>
            ))}
          </div>
          <div className="evidence-foot">
            <span className="muted">
              {new Date(item.retrievedAt).toLocaleString('ja-JP', {
                timeZone: 'Asia/Tokyo',
                dateStyle: 'medium',
                timeStyle: 'short',
              })}
              に確認
            </span>
            <a
              className="ghost-button"
              href={item.canonicalUrl || item.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              <ExternalIcon />
              開く
            </a>
          </div>
        </article>
      ))}

      <button type="button" className="ghost-button wide" onClick={onClose}>
        閉じる
      </button>
    </BottomSheet>
  )
}
