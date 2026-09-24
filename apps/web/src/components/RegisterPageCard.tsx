/**
 * イベントのページを登録する（ADR-014）。
 *
 * 利用者が自分で貼った URL だけを読む。エージェントが robots.txt を確かめてページを読み、
 * 日程を検証して一覧に追加し、以後は毎朝見直す。動きは SSE で 1 行ずつ出す。
 * Web 検索の出典からは登録させない（検索グラウンディングの結果のリンクを使わない）。
 */
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { registerWatchedPage } from '../api/client'
import type { RunActivity, WatchedPageResponse } from '../types/api'

const AGENT_NAME: Record<string, string> = {
  planner: '計画',
  searcher: '読み取り',
  extractor: '抽出',
  organizer: '整理',
}

type Props = { onClose: () => void; onAdded: () => void }

export function RegisterPageCard({ onClose, onAdded }: Props) {
  const navigate = useNavigate()
  const [url, setUrl] = useState('')
  const [pending, setPending] = useState(false)
  const [lines, setLines] = useState<RunActivity[]>([])
  const [result, setResult] = useState<WatchedPageResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const trimmed = url.trim()
    if (!trimmed || pending) return
    setPending(true)
    setLines([])
    setResult(null)
    setError(null)
    try {
      const response = await registerWatchedPage(trimmed, undefined, (line) =>
        setLines((current) => [...current, line]),
      )
      setResult(response)
      if (response.status === 'added') onAdded()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'ページを登録できませんでした。')
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="register-card">
      <div className="web-card-head">
        <p className="eyebrow">イベントのページを登録</p>
        <button type="button" className="link-button" onClick={onClose}>
          閉じる
        </button>
      </div>
      <p className="fine">
        告知ページの URL を貼ると、エージェントがページを読んで日程と締切を確かめ、一覧に追加します。以後は毎朝見直して、変更があれば反映します。
      </p>
      <form className="route-form" onSubmit={onSubmit}>
        <label className="sr-only" htmlFor="register-url">
          イベントのページの URL
        </label>
        <input
          id="register-url"
          type="url"
          inputMode="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://"
          disabled={pending}
        />
        <button type="submit" disabled={pending || !url.trim()}>
          {pending ? '読んでいます…' : '登録する'}
        </button>
      </form>

      {(lines.length > 0 || pending) && (
        <div className="activity-log">
          <ol>
            {lines.map((line, index) => (
              <li key={`${line.at}-${index}`} className={line.level === 'warn' ? 'is-warn' : 'is-done'}>
                <span className="log-icon" aria-hidden="true">
                  {line.level === 'warn' ? '!' : '✓'}
                </span>
                <span className="log-time" />
                <span className="log-agent">{AGENT_NAME[line.agent] ?? line.agent}</span>
                <span className="log-message">{line.message}</span>
              </li>
            ))}
            {pending && (
              <li className="is-running" aria-hidden="true">
                <span className="log-icon">
                  <span className="spinner spinner-sm" />
                </span>
                <span className="log-time" />
                <span className="log-agent">エージェント</span>
                <span className="log-message shimmer">ページを確かめています</span>
              </li>
            )}
          </ol>
        </div>
      )}

      {result && (
        <p className={`fine${result.status === 'rejected' ? ' warn' : ''}`} role="status">
          {result.message}
          {result.event && (
            <>
              {' '}
              <button
                type="button"
                className="link-button"
                onClick={() => navigate(`/events/${encodeURIComponent(result.event!.eventId)}`)}
              >
                「{result.event.title}」を開く
              </button>
            </>
          )}
        </p>
      )}
      {error && (
        <p className="fine warn" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
