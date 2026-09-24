/**
 * S-02 イベント詳細。
 *
 * 根拠（§7.2）はシートに隠さず本文に並べる。外部ページ由来の文字列は信頼できない
 * データとして扱い、HTMLとして解釈せずテキストで出す（§10.1）。
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { goUrl, listEvidence } from '../api/client'
import { useAppState } from '../state/AppState'
import {
  categoryLabel,
  formatLocationType,
  hostOf,
  isCalendarRegistered,
  missingFields,
  placeLabel,
} from '../lib/eventView'
import { DualDateBlock } from '../components/DualDateBlock'
import { CalendarSheet } from '../components/CalendarSheet'
import { EventMap, mapsSearchUrl } from '../components/EventMap'
import { RoutePanel } from '../components/RoutePanel'
import type { Event, Evidence } from '../types/api'

const SOURCE_LABEL: Record<Evidence['sourceType'], string> = {
  official: '公式',
  organizer: '主催者',
  aggregator: '集約サイト',
  other: 'その他',
}

type EvidenceGroup = { url: string; sourceType: Evidence['sourceType']; excerpts: string[] }

/** 同じページからの根拠はまとめて、リンク1つに抜粋を並べる。 */
function groupEvidence(items: Evidence[]): EvidenceGroup[] {
  const groups = new Map<string, EvidenceGroup>()
  for (const item of items) {
    const url = item.canonicalUrl || item.sourceUrl
    const group = groups.get(url) ?? { url, sourceType: item.sourceType, excerpts: [] }
    if (item.excerpt && !group.excerpts.includes(item.excerpt)) group.excerpts.push(item.excerpt)
    groups.set(url, group)
  }
  return [...groups.values()]
}

export function EventDetailScreen() {
  const { eventId = '' } = useParams()
  const navigate = useNavigate()
  const { eventById, postByEventId, loadState, saved, calendar, toggleSaved, register } =
    useAppState()
  const [sheetEvent, setSheetEvent] = useState<Event | null>(null)
  const [evidence, setEvidence] = useState<Evidence[] | null>(null)
  const [evidenceError, setEvidenceError] = useState<string | null>(null)

  const event = eventById(eventId)
  const post = postByEventId(eventId)
  const found = event !== undefined
  const evidenceGroups = useMemo(() => (evidence ? groupEvidence(evidence) : []), [evidence])
  const evidenceCount = event?.evidenceIds.length ?? 0

  useEffect(() => {
    if (!found) return
    let cancelled = false
    setEvidence(null)
    setEvidenceError(null)
    // 投稿由来のイベントは根拠を投稿に埋め込んでいる（ADR-006）。API には無い
    if (post) {
      setEvidence(post.evidence)
      return
    }
    if (evidenceCount === 0) {
      setEvidence([])
      return
    }
    listEvidence(eventId)
      .then((result) => {
        if (!cancelled) setEvidence(result.evidence)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setEvidenceError(caught instanceof Error ? caught.message : '根拠を取得できませんでした。')
        }
      })
    return () => {
      cancelled = true
    }
    // イベントが差し替わったとき、または一覧の再読込で根拠の件数が変わったときだけ取り直す
  }, [eventId, found, evidenceCount, post])

  // 直接URLで開いたときは履歴が無いので、戻る先を一覧に固定する
  const goBack = () => {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0
    if (idx > 0) navigate(-1)
    else navigate('/')
  }

  if (!event) {
    return (
      <div className="detail">
        <button type="button" className="back" onClick={goBack}>
          ← 一覧へ
        </button>
        <p className="empty">
          {loadState === 'ready' ? (
            <>
              イベントが見つかりません。
              <br />
              一覧が更新された可能性があります。
            </>
          ) : (
            '読み込んでいます…'
          )}
        </p>
      </div>
    )
  }

  const partial = event.validationStatus === 'partial'
  const missing = missingFields(event)
  const isSaved = Boolean(saved[event.eventId])
  const registered = isCalendarRegistered(calendar[event.eventId])
  const showApplication = Boolean(
    event.applicationUrl && event.applicationUrl !== event.officialUrl,
  )
  // 会場名と地域を並べて検索語にする。座標は持たないので、地図側の検索に任せる
  const placeQuery = [event.location.venue, event.location.region]
    .filter((part, index, parts) => part && parts.indexOf(part) === index)
    .join(' ')

  return (
    <div className="detail">
      <button type="button" className="back" onClick={goBack}>
        ← 一覧へ
      </button>

      <div className="detail-title">
        <p className="eyebrow">
          {categoryLabel(event.category)}
          {post && ' · 主催者投稿'}
          {(post?.organizerConfirmed || event.organizerEdit) && (
            <span className="tag tag-verified">✓ 主催者確認済み</span>
          )}
        </p>
        <h1>{event.title}</h1>
        <p className="detail-meta">
          {event.organizer || '主催者未確認'} · {placeLabel(event)} ·{' '}
          {formatLocationType(event.location.type)}
          {event.recommendation && ` · 適合 ${event.recommendation.score}`}
        </p>
      </div>

      <section className="detail-dates">
        <DualDateBlock event={event} size="detail" />
        {partial && (
          <p className="fine warn">
            未確認: {missing.join('、')} — 公式サイトでご確認ください。
          </p>
        )}
        {event.dates.applicationDeadlinePrecision === 'date' && event.dates.applicationDeadline && (
          <p className="fine">締切は日付のみ確認しています（時刻は未確認）。</p>
        )}
      </section>

      <p className="detail-summary">{event.summary}</p>

      {/* ジャンル固有の値（賞金・支援内容・対象ステージ…）。ページの行をそのまま出す */}
      {Object.keys(event.attributes ?? {}).length > 0 && (
        <section className="attributes">
          <p className="eyebrow">募集要項</p>
          <dl className="attribute-list">
            {Object.entries(event.attributes ?? {}).map(([label, value]) => (
              <div className="attribute-row" key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}
      {event.recommendation?.reason && (
        <p className="detail-reason">{event.recommendation.reason}</p>
      )}

      <section className="evidence">
        <p className="eyebrow">根拠</p>
        {evidenceError && <p className="fine warn">{evidenceError}</p>}
        {!evidence && !evidenceError && <p className="fine">読み込んでいます…</p>}
        {evidence?.length === 0 && (
          <p className="fine">根拠を取得できませんでした。公式サイトでご確認ください。</p>
        )}
        {evidenceGroups.map((group) => (
          <div className="evidence-item" key={group.url}>
            <a href={group.url} target="_blank" rel="noopener noreferrer">
              {hostOf(group.url)}
              <span className="evidence-kind">{SOURCE_LABEL[group.sourceType]}</span>
            </a>
            {group.excerpts.length > 0 && (
              <p className="evidence-quote">
                {group.excerpts.map((excerpt) => `「${excerpt}」`).join(' ')}
              </p>
            )}
          </div>
        ))}
      </section>

      {/* 開催場所: 地図 + 駅すぱあと経路（ADR-001）。オンライン開催では出さない。 */}
      {event.location.type !== 'online' && (event.location.venue || event.location.region) && (
        <section className="place">
          <p className="eyebrow">開催場所</p>
          <p className="place-name">
            {event.location.venue || event.location.region}
            {event.location.type === 'hybrid' && <span className="tag">オンライン併催</span>}
          </p>
          <EventMap query={placeQuery} />
          <p className="fine">
            <a href={mapsSearchUrl(placeQuery)} target="_blank" rel="noopener noreferrer">
              Google マップで開く
            </a>
            {event.location.nearestStation
              ? ` · 最寄駅: ${event.location.nearestStation}`
              : ' · 最寄駅は未確認'}
          </p>
          <RoutePanel
            eventId={event.eventId}
            nearestStation={event.location.nearestStation || ''}
            venue={event.location.venue || event.location.region || undefined}
          />
        </section>
      )}

      {/* 主催者の申請（ADR-013）。AI が集めたイベントを主催者が確かめて直す */}
      {!post && (
        <section className="organizer-cta">
          <p>
            {event.organizerEdit
              ? `主催者が情報を確認・更新しました（${new Date(
                  event.organizerEdit.editedAt ?? event.organizerEdit.verifiedAt,
                ).toLocaleDateString('ja-JP', { timeZone: 'Asia/Tokyo' })}）。`
              : 'このイベントの主催者の方へ: 最寄駅や申込締切が違っていたら直せます。'}
          </p>
          <Link to={`/events/${encodeURIComponent(event.eventId)}/manage`}>
            {event.organizerEdit ? '主催者として編集する' : 'このイベントを申請する'}
          </Link>
        </section>
      )}

      <div className="detail-actions">
        <button type="button" className="button button-primary" onClick={() => setSheetEvent(event)}>
          {registered ? '登録内容を変更' : 'カレンダーに登録'}
        </button>
        <button
          type="button"
          className="button"
          aria-pressed={isSaved}
          onClick={() => toggleSaved(event.eventId)}
        >
          {isSaved ? '保存済' : '保存'}
        </button>
        <a
          className="button"
          href={goUrl(event.eventId, post ? 'contact' : 'official')}
          target="_blank"
          rel="noopener noreferrer"
        >
          公式サイト
        </a>
        {showApplication && (
          <a
            className="button"
            href={goUrl(event.eventId, 'application')}
            target="_blank"
            rel="noopener noreferrer"
          >
            申込ページ
          </a>
        )}
      </div>

      <CalendarSheet event={sheetEvent} onClose={() => setSheetEvent(null)} onConfirm={register} />
    </div>
  )
}
