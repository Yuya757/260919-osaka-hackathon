/**
 * S-10 投稿フォーム（F-06）。
 *
 * 2段階。まず本文を送って抽出結果を見せ（preview、何も保存しない）、
 * 締切が無い・重複しているなどの指摘を確認してから投稿する。
 * S-07 のカレンダー登録と同じ「決めてから確定」の流れ。
 */
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { previewOrganizerPost } from '../api/client'
import { useAppState } from '../state/AppState'
import { categoryLabel, formatLocationType, placeLabel } from '../lib/eventView'
import { DualDateBlock } from '../components/DualDateBlock'
import type { OrganizerPostPreviewResponse, OrganizerPostRequest } from '../types/api'

const BODY_PLACEHOLDER = `生成AIをテーマにした2泊3日のハッカソンです。
開催日: 2026年10月16日 10:00 〜 2026年10月18日 18:00
申込締切: 2026年9月30日 23:59
会場: グランフロント大阪`

const EMPTY: OrganizerPostRequest = { organizerName: '', contactUrl: '', title: '', body: '' }

export function PostFormScreen() {
  const navigate = useNavigate()
  const { createPost } = useAppState()
  const [draft, setDraft] = useState<OrganizerPostRequest>(EMPTY)
  const [preview, setPreview] = useState<OrganizerPostPreviewResponse | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')

  const update = (key: keyof OrganizerPostRequest, value: string) => {
    setDraft((current) => ({ ...current, [key]: value }))
    setError('')
  }

  const trimmed = (): OrganizerPostRequest => ({
    organizerName: draft.organizerName.trim(),
    contactUrl: draft.contactUrl.trim(),
    title: draft.title.trim(),
    body: draft.body.trim(),
  })

  const onPreview = async (event: FormEvent) => {
    event.preventDefault()
    if (pending) return
    setPending(true)
    setError('')
    try {
      const result = await previewOrganizerPost(trimmed())
      setPreview(result)
      if (!result.event) {
        // 開催日が取れない等。確認画面には進まず、本文の直し方を出す
        setError(result.issues.map((issue) => issue.message).join(' '))
        setPreview(null)
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '確認に失敗しました。')
    } finally {
      setPending(false)
    }
  }

  const onSubmit = async () => {
    if (pending) return
    setPending(true)
    setError('')
    try {
      await createPost(trimmed())
      navigate('/feed')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '投稿に失敗しました。')
    } finally {
      setPending(false)
    }
  }

  const warnings = preview?.issues.filter((issue) => issue.severity === 'warning') ?? []

  if (preview?.event) {
    const event = preview.event
    return (
      <div className="post-form">
        <button type="button" className="back" onClick={() => setPreview(null)}>
          ← 本文を直す
        </button>
        <div className="post-confirm">
          <p className="eyebrow">投稿内容の確認</p>
          <h1>{draft.title.trim()}</h1>
          <p className="detail-meta">
            {draft.organizerName.trim()} · {placeLabel(event)} · {formatLocationType(event.location.type)} ·{' '}
            {categoryLabel(event.category)}
          </p>
          <div className="detail-dates">
            <DualDateBlock event={event} size="detail" />
          </div>
          {warnings.length > 0 && (
            <ul className="post-warnings">
              {warnings.map((issue) => (
                <li key={issue.code}>{issue.message}</li>
              ))}
            </ul>
          )}
          {error && (
            <p className="fine warn" role="alert">
              {error}
            </p>
          )}
          <div className="detail-actions">
            <button
              type="button"
              className="button button-primary"
              disabled={pending}
              onClick={() => void onSubmit()}
            >
              {pending ? '投稿しています…' : warnings.length ? 'そのまま投稿' : 'この内容で投稿'}
            </button>
            <button type="button" className="button" onClick={() => setPreview(null)}>
              本文を直す
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="post-form">
      <button type="button" className="back" onClick={() => navigate('/feed')}>
        ← フィードへ
      </button>
      <div className="post-head">
        <h1>イベントを投稿する</h1>
        <p className="fine">
          本文から申込締切と開催日を読み取り、そのまま一覧に載ります。年を含めて書いてください。読み取れない値は推測しません。
        </p>
      </div>

      <form className="form" onSubmit={onPreview}>
        <label className="field">
          <span>主催者名</span>
          <input
            value={draft.organizerName}
            maxLength={80}
            required
            autoComplete="organization"
            onChange={(event) => update('organizerName', event.target.value)}
          />
        </label>
        <label className="field">
          <span>連絡先・公式サイトのURL</span>
          <input
            type="url"
            value={draft.contactUrl}
            maxLength={2048}
            required
            inputMode="url"
            placeholder="https://"
            onChange={(event) => update('contactUrl', event.target.value)}
          />
        </label>
        <label className="field">
          <span>タイトル</span>
          <input
            value={draft.title}
            maxLength={120}
            required
            onChange={(event) => update('title', event.target.value)}
          />
        </label>
        <label className="field">
          <span>本文</span>
          <textarea
            value={draft.body}
            rows={8}
            maxLength={4000}
            required
            placeholder={BODY_PLACEHOLDER}
            onChange={(event) => update('body', event.target.value)}
          />
          <small>「開催日:」「申込締切:」「会場:」の行があると、そのまま日程と場所になります。</small>
        </label>

        {error && (
          <p className="fine warn field-error" role="alert">
            {error}
          </p>
        )}

        <div className="detail-actions">
          <button type="submit" className="button button-primary" disabled={pending}>
            {pending ? '確認しています…' : '内容を確認する'}
          </button>
          <button type="button" className="button" onClick={() => navigate('/feed')}>
            やめる
          </button>
        </div>
      </form>
    </div>
  )
}
