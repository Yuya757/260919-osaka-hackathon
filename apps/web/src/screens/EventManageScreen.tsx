/**
 * 主催者の方へ（ADR-013）。イベントを申請し、本人確認のうえ情報を直す。
 *
 * ログインは無い。確認コードをイベントページ（connpass・Doorkeeper・公式サイト）に
 * 一時的に書いてもらい、エージェントがそのページを読みに行って確かめる。
 * 確かめられたら編集用の鍵がこの端末に保存され、最寄駅・会場・申込締切・申込ページを直せる。
 */
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { editClaimedEvent, startEventClaim, verifyEventClaim } from '../api/client'
import { loadClaim, saveClaim, type StoredClaim } from '../lib/claims'
import { hostOf } from '../lib/eventView'
import { useAppState } from '../state/AppState'
import type { Event } from '../types/api'

const JST_OFFSET = '+09:00'

/** ISO 日時 → datetime-local の値（JST）。 */
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const jst = new Date(new Date(iso).getTime() + 9 * 3600_000)
  return jst.toISOString().slice(0, 16)
}

/** datetime-local の値（JST として読む）→ ISO 日時 */
function fromLocalInput(value: string): string | null {
  return value ? `${value}:00${JST_OFFSET}` : null
}

function EditForm({ event, claim }: { event: Event; claim: StoredClaim }) {
  const { refresh } = useAppState()
  const [station, setStation] = useState(event.location.nearestStation ?? '')
  const [venue, setVenue] = useState(event.location.venue ?? '')
  const [deadline, setDeadline] = useState(toLocalInput(event.dates.applicationDeadline))
  const [applicationUrl, setApplicationUrl] = useState(
    event.applicationUrl && event.applicationUrl !== event.officialUrl ? event.applicationUrl : '',
  )
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)

  const onSubmit = async (formEvent: FormEvent) => {
    formEvent.preventDefault()
    if (!claim.editToken || pending) return
    setPending(true)
    setMessage(null)
    try {
      await editClaimedEvent(claim.claimId, claim.editToken, {
        nearestStation: station.trim() || null,
        venue: venue.trim() || null,
        applicationDeadline: fromLocalInput(deadline),
        applicationUrl: applicationUrl.trim() || null,
      })
      await refresh()
      setMessage({ tone: 'ok', text: '保存しました。一覧と詳細に反映されています。' })
    } catch (caught) {
      setMessage({
        tone: 'error',
        text: caught instanceof Error ? caught.message : '保存できませんでした。',
      })
    } finally {
      setPending(false)
    }
  }

  return (
    <form className="manage-form" onSubmit={onSubmit}>
      <p className="manage-verified">
        <span aria-hidden="true">✓</span> 主催者として確認済みです
      </p>
      <label>
        <span>最寄駅</span>
        <input
          value={station}
          onChange={(e) => setStation(e.target.value)}
          placeholder="例: 梅田"
          maxLength={40}
        />
      </label>
      <label>
        <span>会場</span>
        <input
          value={venue}
          onChange={(e) => setVenue(e.target.value)}
          placeholder="例: グランフロント大阪 ナレッジキャピタル"
          maxLength={120}
        />
      </label>
      <label>
        <span>申込締切（日本時間）</span>
        <input type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
      </label>
      <label>
        <span>申込ページ</span>
        <input
          type="url"
          value={applicationUrl}
          onChange={(e) => setApplicationUrl(e.target.value)}
          placeholder="https://"
        />
      </label>
      <p className="fine">空欄の項目は、AI が集めた値のまま変えません。</p>
      <button type="submit" className="button button-primary" disabled={pending}>
        {pending ? '保存中…' : '保存する'}
      </button>
      {message && (
        <p className={`fine${message.tone === 'error' ? ' warn' : ''}`} role="status">
          {message.text}
        </p>
      )}
    </form>
  )
}

export function EventManageScreen() {
  const { eventId = '' } = useParams()
  const navigate = useNavigate()
  const { eventById } = useAppState()
  const event = eventById(eventId)
  const [claim, setClaim] = useState<StoredClaim | null>(() => loadClaim(eventId))
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  if (!event) {
    return (
      <div className="detail">
        <button type="button" className="back" onClick={() => navigate('/')}>
          ← 一覧へ
        </button>
        <p className="empty">イベントが見つかりません。</p>
      </div>
    )
  }

  const remember = (next: StoredClaim | null) => {
    setClaim(next)
    if (!saveClaim(eventId, next)) {
      setMessage('ブラウザに保存できませんでした。プライベートウィンドウでは、鍵が残りません。')
    }
  }

  const onStart = async () => {
    setPending(true)
    setMessage(null)
    try {
      const started = await startEventClaim(eventId)
      remember({
        claimId: started.claimId,
        editToken: null,
        code: started.code,
        pageUrls: started.pageUrls,
        expiresAt: started.expiresAt,
      })
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : '申請を始められませんでした。')
    } finally {
      setPending(false)
    }
  }

  const onVerify = async () => {
    if (!claim) return
    setPending(true)
    setMessage(null)
    try {
      const result = await verifyEventClaim(claim.claimId)
      if (result.status === 'verified' && result.editToken) {
        remember({ ...claim, editToken: result.editToken, tokenExpiresAt: result.tokenExpiresAt })
      } else if (result.status === 'expired' || result.status === 'too_many_attempts') {
        remember(null)
        setMessage(result.message)
      } else {
        setMessage(result.message)
      }
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : '確認できませんでした。')
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="detail manage">
      <Link className="back" to={`/events/${encodeURIComponent(eventId)}`}>
        ← イベントへ
      </Link>
      <div className="detail-title">
        <p className="eyebrow">主催者の方へ</p>
        <h1>{event.title}</h1>
        <p className="detail-meta">
          最寄駅や申込締切が違っていたら、主催者であることを確認したうえで直せます。
          直した値は「主催者確認済み」として表示されます。
        </p>
      </div>

      {claim?.editToken ? (
        <EditForm event={event} claim={claim} />
      ) : claim ? (
        <section className="manage-steps">
          <ol>
            <li>
              <p>次の確認コードを、イベントページの説明文などに一時的に書いて公開してください。</p>
              <p className="manage-code" aria-label="確認コード">
                {claim.code}
              </p>
            </li>
            <li>
              <p>コードを書いたページ（どれか 1 つで構いません）</p>
              <ul className="manage-pages">
                {claim.pageUrls.map((url) => (
                  <li key={url}>
                    <a href={url} target="_blank" rel="noopener noreferrer">
                      {hostOf(url)}
                    </a>
                  </li>
                ))}
              </ul>
            </li>
            <li>
              <p>書けたら「ページを確認する」を押してください。エージェントがページを読みに行きます。確認が済んだらコードは消して構いません。</p>
            </li>
          </ol>
          <div className="detail-actions">
            <button type="button" className="button button-primary" onClick={onVerify} disabled={pending}>
              {pending ? '確認しています…' : 'ページを確認する'}
            </button>
            <button type="button" className="button" onClick={() => remember(null)} disabled={pending}>
              やり直す
            </button>
          </div>
          <p className="fine">
            コードの期限:{' '}
            {new Date(claim.expiresAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}
          </p>
        </section>
      ) : (
        <section className="manage-steps">
          <p>
            このイベントのページ（{hostOf(event.officialUrl)}）を編集できる方が主催者です。
            確認コードを発行して、ページに書いてもらうことで確かめます。
          </p>
          <div className="detail-actions">
            <button type="button" className="button button-primary" onClick={onStart} disabled={pending}>
              {pending ? '発行しています…' : '確認コードを発行する'}
            </button>
          </div>
        </section>
      )}

      {message && (
        <p className="fine warn" role="alert">
          {message}
        </p>
      )}
    </div>
  )
}
