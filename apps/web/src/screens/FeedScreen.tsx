/**
 * S-09 投稿フィード（F-06）。
 *
 * AI が検証した一覧とは別物として、主催者からの投稿をそのまま並べる。
 * Slack のチャンネルのように古い順に流し、日付で区切る（最新が一番下）。
 * PR の固定枠は上にまとめる。「主催者投稿」「ボット投稿」は名前の横で分かるようにする。
 * カレンダー登録は一覧と同じ承認シートを通す。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { goUrl } from '../api/client'
import {
  formatLocationType,
  hostOf,
  isCalendarRegistered,
  needsCheck,
  placeLabel,
} from '../lib/eventView'
import {
  avatarInitial,
  avatarTone,
  capacityOf,
  excerpt,
  feedTimeline,
  placementLabel,
  postedAtLabel,
  postedTimeLabel,
  profileMatches,
  type Capacity,
} from '../lib/feedView'
import { loadProfile } from '../lib/profile'
import { DualDateBlock } from '../components/DualDateBlock'
import { CalendarSheet } from '../components/CalendarSheet'
import type { Event, OrganizerPost } from '../types/api'

/** 定員と申込人数。両方あれば埋まり具合を棒で見せる */
function CapacityLine({ capacity }: { capacity: Capacity }) {
  const { limit, registered, asOf } = capacity
  const ratio = limit && registered !== null ? Math.min(registered / limit, 1) : null
  const left = limit !== null && registered !== null ? limit - registered : null
  const asOfLabel = asOf ? `${postedAtLabel(asOf)} ${postedTimeLabel(asOf)}時点` : ''
  return (
    <div className="msg-capacity">
      <span className="msg-capacity-text">
        {registered !== null && limit !== null ? (
          <>
            申込 <strong>{registered}</strong> / 定員 {limit}人
            <span className={left !== null && left <= 0 ? 'is-full' : ''}>
              {left !== null && (left > 0 ? `・残り${left}席` : '・満席')}
            </span>
          </>
        ) : limit !== null ? (
          <>定員 {limit}人</>
        ) : (
          <>申込 <strong>{registered}</strong>人</>
        )}
      </span>
      {ratio !== null && (
        <span
          className="msg-capacity-bar"
          role="img"
          aria-label={`定員の${Math.round(ratio * 100)}%が埋まっています`}
        >
          <span style={{ width: `${Math.round(ratio * 100)}%` }} />
        </span>
      )}
      {asOfLabel && <span className="msg-capacity-asof">{asOfLabel}</span>}
    </div>
  )
}

export function FeedScreen() {
  const { posts, postsState, postsError, refreshPosts, saved, calendar, toggleSaved, register } =
    useAppState()
  const [sheetEvent, setSheetEvent] = useState<Event | null>(null)
  const navigate = useNavigate()
  const profile = useMemo(() => loadProfile().profile, [])
  const endRef = useRef<HTMLDivElement>(null)

  const matches = useMemo(
    () => new Map(posts.map((post) => [post.postId, profileMatches(post, profile)])),
    [posts, profile],
  )
  const timeline = useMemo(() => feedTimeline(posts), [posts])

  // チャンネルを開いたときのように、最新の投稿（一番下）から見せる
  useEffect(() => {
    if (postsState === 'ready' && posts.length) endRef.current?.scrollIntoView({ block: 'end' })
  }, [postsState, posts.length])

  const renderPost = (post: OrganizerPost) => {
    const { event } = post
    const hits = matches.get(post.postId) ?? []
    const pinned = placementLabel(post)
    const registered = isCalendarRegistered(calendar[event.eventId])
    const isSaved = Boolean(saved[event.eventId])
    const partial = needsCheck(event)
    const capacity = capacityOf(post)
    const bot = post.origin === 'bot'
    const summary = excerpt(post.body)
    return (
      <article
        key={post.postId}
        className={[
          'msg',
          hits.length ? 'is-match' : '',
          pinned ? 'is-sponsor' : '',
          post.organizerConfirmed ? 'is-verified' : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        {/* アイコンは主催者ごとに決まる。ボットかどうかは名前の横のバッジで示す */}
        <span className={`msg-avatar tone-${avatarTone(post.organizerName)}`} aria-hidden="true">
          {avatarInitial(post.organizerName)}
        </span>
        <div className="msg-main">
          <p className="msg-head">
            <span className="msg-name">{post.organizerName}</span>
            {bot ? (
              <span className="msg-badge">ボット</span>
            ) : (
              post.organizerConfirmed && (
                <span className="msg-badge is-confirmed">
                  <span aria-hidden="true">✓</span> 主催者確認済み
                </span>
              )
            )}
            <time className="msg-time" dateTime={post.createdAt}>
              {pinned ? postedAtLabel(post.createdAt) + ' ' : ''}
              {postedTimeLabel(post.createdAt)}
            </time>
            {pinned && <span className="msg-badge is-sponsor">{pinned}</span>}
          </p>
          <button
            type="button"
            className="msg-title"
            onClick={() => navigate(`/events/${encodeURIComponent(event.eventId)}`)}
          >
            {post.title}
          </button>
          {summary && <p className="msg-text">{summary}</p>}

          {/* Slack の添付のように、日程と会場と定員を左の線で束ねる */}
          <div className="msg-attachment">
            <p className="msg-meta">
              {placeLabel(event)} · {formatLocationType(event.location.type)} ·{' '}
              <a
                href={goUrl(event.eventId, bot ? 'official' : 'contact')}
                target="_blank"
                rel="noopener noreferrer nofollow"
              >
                {hostOf(post.contactUrl)}
              </a>
              {partial && <span className="tag">要確認</span>}
            </p>
            <DualDateBlock event={event} />
            {capacity && <CapacityLine capacity={capacity} />}
          </div>

          {(hits.length > 0 || (!bot && post.linkedEventId)) && (
            <p className="msg-notes">
              {hits.length > 0 && <span className="tag tag-match">関心に合う: {hits.join('・')}</span>}
              {!bot && post.linkedEventId && (
                <Link to={`/events/${encodeURIComponent(post.linkedEventId)}`}>
                  AI収集の一覧にも同じイベントがあります
                </Link>
              )}
            </p>
          )}

          <div className="msg-actions">
            <button
              type="button"
              className={`chip-button${isSaved ? ' is-on' : ''}`}
              aria-pressed={isSaved}
              onClick={() => toggleSaved(event.eventId)}
            >
              {isSaved ? '保存済' : '保存'}
            </button>
            <button
              type="button"
              className={`chip-button${registered ? ' is-on' : ''}`}
              onClick={() => setSheetEvent(event)}
            >
              {registered ? '登録済' : '登録'}
            </button>
          </div>
        </div>
      </article>
    )
  }

  return (
    <>
      <div className="feed-head">
        <div className="feed-head-row">
          <h1>
            <span className="channel-hash" aria-hidden="true">
              #
            </span>
            主催者投稿
          </h1>
          <span className="next-count">{posts.length}件</span>
          <span className="spacer" />
          <Link to="/feed/new" className="button button-primary">
            投稿する
          </Link>
        </div>
        <p className="fine">
          AI収集の一覧とは別に、主催者からの投稿をそのまま並べています。日程は投稿文から読み取ったもので、申込前に公式サイトをご確認ください。
        </p>
      </div>

      {postsState === 'loading' && (
        <div aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div className="skeleton-row" key={i} aria-hidden="true" />
          ))}
        </div>
      )}

      {postsState === 'error' && (
        <div className="empty">
          <p>
            <strong>投稿を取得できませんでした</strong>
            <br />
            {postsError}
          </p>
          <button type="button" className="button" onClick={() => void refreshPosts()}>
            再試行
          </button>
        </div>
      )}

      {postsState === 'ready' &&
        (posts.length === 0 ? (
          <p className="empty">
            まだ投稿はありません。
            <br />
            最初の告知を投稿するか、毎朝の自動収集を待つと AI が集めたイベントがボット投稿として並びます。
          </p>
        ) : (
          <div className="channel">
            {timeline.pinned.length > 0 && (
              <section className="channel-pinned" aria-label="固定された投稿">
                <p className="channel-pinned-label">固定</p>
                {timeline.pinned.map(renderPost)}
              </section>
            )}
            {timeline.days.map((day) => (
              <section key={day.key} aria-label={day.label}>
                <div className="day-divider">
                  <span>{day.label}</span>
                </div>
                {day.posts.map(renderPost)}
              </section>
            ))}
            <div ref={endRef} />
          </div>
        ))}

      <CalendarSheet event={sheetEvent} onClose={() => setSheetEvent(null)} onConfirm={register} />
    </>
  )
}
