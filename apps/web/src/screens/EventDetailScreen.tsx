/** S-02 イベント詳細 */
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import {
  categoryLabel,
  formatLocationType,
  hostOf,
  missingFields,
} from '../lib/eventView'
import { CalendarBadge, UrgentBadge, ValidationBadge } from '../components/Badges'
import { DualDateBlock } from '../components/DualDateBlock'
import { CalendarSheet } from '../components/CalendarSheet'
import { EvidenceSheet } from '../components/EvidenceSheet'
import { RunProgressBanner } from '../components/RunProgressBanner'
import { RoutePanel } from '../components/RoutePanel'
import { BackIcon, CalendarIcon, ExternalIcon, HeartIcon } from '../components/Icon'
import type { Event } from '../types/api'

export function EventDetailScreen() {
  const { eventId = '' } = useParams()
  const navigate = useNavigate()
  const { eventById, saved, calendar, toggleSaved, register } = useAppState()
  const [sheetEvent, setSheetEvent] = useState<Event | null>(null)
  const [evidenceFor, setEvidenceFor] = useState<string | null>(null)

  const event = eventById(eventId)

  if (!event) {
    return (
      <>
        <header className="app-header">
          <button type="button" className="icon-button" onClick={() => navigate('/')} aria-label="戻る">
            <BackIcon />
          </button>
          <div className="header-main">
            <h1 className="header-compact">イベント詳細</h1>
          </div>
        </header>
        <div className="scroll-area">
          <div className="empty">
            <strong>イベントが見つかりません</strong>
            <p>一覧が更新された可能性があります。</p>
            <button type="button" className="primary-button" onClick={() => navigate('/')}>
              ホームへ戻る
            </button>
          </div>
        </div>
      </>
    )
  }

  const partial = event.validationStatus === 'partial'
  const missing = missingFields(event)
  const isSaved = Boolean(saved[event.eventId])
  const aggregatorOnly = event.source?.includes('集約') ?? false

  return (
    <>
      <header className="app-header">
        <button type="button" className="icon-button" onClick={() => navigate(-1)} aria-label="戻る">
          <BackIcon />
        </button>
        <div className="header-main">
          <h1 className="header-compact">イベント詳細</h1>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-pressed={isSaved}
          aria-label={isSaved ? '保存を解除' : '保存する'}
          onClick={() => toggleSaved(event.eventId)}
        >
          <HeartIcon filled={isSaved} />
        </button>
      </header>

      <RunProgressBanner />

      <div className="scroll-area">
        <div className="detail">
          {partial && (
            <div className="notice">
              <strong>△ 一部の情報を確認できていません</strong>
              <p>開催日と根拠は確認済みです。不足している項目は公式サイトでご確認ください。</p>
              <ul>
                {missing.map((field) => (
                  <li key={field}>未確認: {field}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="detail-title">
            <div className="chip-row">
              <span className="chip chip-category">{categoryLabel(event.category)}</span>
              <UrgentBadge event={event} />
              <ValidationBadge status={event.validationStatus} />
            </div>
            <h2>{event.title}</h2>
            <p className="event-meta">{event.organizer || '主催者未確認'}</p>
          </div>

          <section className="panel">
            <h3>日程</h3>
            <DualDateBlock event={event} size="detail" />
            <p className="fine">
              タイムゾーン: {event.dates.timezone}
              {event.dates.applicationDeadlinePrecision === 'date' &&
                ' ／ 締切は日付のみ確認（時刻は未確認）'}
            </p>
            <button
              type="button"
              className="ghost-button wide"
              disabled={event.evidenceIds.length === 0}
              onClick={() => setEvidenceFor(event.eventId)}
            >
              根拠を見る（{event.evidenceIds.length}件）
            </button>
          </section>

          <section className="panel">
            <h3>概要</h3>
            <p>{event.summary}</p>
          </section>

          {event.recommendation && (
            <section className="panel">
              <h3>あなたへの適合 {event.recommendation.score}%</h3>
              <p>{event.recommendation.reason}</p>
            </section>
          )}

          <section className="panel">
            <h3>開催情報</h3>
            <dl className="definitions">
              <dt>形式</dt>
              <dd>{formatLocationType(event.location.type)}</dd>
              <dt>会場</dt>
              <dd>{event.location.venue || '未確認'}</dd>
              <dt>地域</dt>
              <dd>{event.location.region || '未確認'}</dd>
            </dl>
            {/* 駅すぱあと経路検索（ADR-001）。オンライン開催では出さない。 */}
            {event.location.type !== 'online' && event.location.nearestStation && (
              <RoutePanel
                eventId={event.eventId}
                nearestStation={event.location.nearestStation}
              />
            )}
          </section>

          <section className="panel">
            <h3>リンク</h3>
            <a className="link-row" href={event.officialUrl} target="_blank" rel="noopener noreferrer">
              <span className="chip">{aggregatorOnly ? '集約' : '公式'}</span>
              <span className="link-host">{hostOf(event.officialUrl)}</span>
              <ExternalIcon />
            </a>
            {event.applicationUrl && (
              <a
                className="link-row"
                href={event.applicationUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                <span className="chip">申込</span>
                <span className="link-host">{hostOf(event.applicationUrl)}</span>
                <ExternalIcon />
              </a>
            )}
            {aggregatorOnly && (
              <p className="fine warn-text">
                公式ページを確認できていません（集約サイトの情報です）。
              </p>
            )}
          </section>

          <section className="panel">
            <h3>信頼度</h3>
            <div className="confidence">
              <div className="confidence-bar">
                <i
                  className={partial ? 'is-partial' : ''}
                  style={{ width: `${Math.round(event.confidence * 100)}%` }}
                />
                <u style={{ left: '80%' }} aria-hidden="true" />
              </div>
              <p className="fine">
                {Math.round(event.confidence * 100)}%（縦線は確認済みとする閾値 80%）
              </p>
            </div>
          </section>

          <details className="panel">
            <summary>検証情報</summary>
            <dl className="definitions">
              <dt>検証状態</dt>
              <dd>{event.validationStatus}</dd>
              <dt>最終確認</dt>
              <dd>
                {new Date(event.lastSeenAt).toLocaleString('ja-JP', {
                  timeZone: 'Asia/Tokyo',
                  dateStyle: 'medium',
                  timeStyle: 'short',
                })}
              </dd>
              <dt>収集Run</dt>
              <dd className="mono">{event.sourceRunId}</dd>
            </dl>
          </details>
        </div>
      </div>

      <div className="action-bar">
        <CalendarBadge ids={calendar[event.eventId]} />
        <span className="spacer" />
        <button type="button" className="primary-button" onClick={() => setSheetEvent(event)}>
          <CalendarIcon />
          {calendar[event.eventId] ? '登録内容を変更' : 'カレンダーに登録'}
        </button>
      </div>

      <CalendarSheet event={sheetEvent} onClose={() => setSheetEvent(null)} onConfirm={register} />
      <EvidenceSheet eventId={evidenceFor} onClose={() => setEvidenceFor(null)} />
    </>
  )
}
