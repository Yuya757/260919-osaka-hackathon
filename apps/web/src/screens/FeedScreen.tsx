/**
 * S-09 投稿フィード（F-06）。
 *
 * AI が検証した一覧とは別物として、主催者からの投稿をそのまま並べる。
 * 行の見た目は一覧と揃えるが、「主催者投稿」「ボット投稿」と分かるようにする。
 * カレンダー登録は一覧と同じ承認シートを通す。
 */
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { goUrl } from '../api/client'
import { formatLocationType, hostOf, isCalendarRegistered, placeLabel } from '../lib/eventView'
import { excerpt, originLabel, placementLabel, postedAtLabel, profileMatches } from '../lib/feedView'
import { loadProfile } from '../lib/profile'
import { DualDateBlock } from '../components/DualDateBlock'
import { CalendarSheet } from '../components/CalendarSheet'
import type { Event, OrganizerPost } from '../types/api'

export function FeedScreen() {
  const { posts, postsState, postsError, refreshPosts, saved, calendar, toggleSaved, register } =
    useAppState()
  const [sheetEvent, setSheetEvent] = useState<Event | null>(null)
  const navigate = useNavigate()
  const profile = useMemo(() => loadProfile().profile, [])

  const matches = useMemo(
    () => new Map(posts.map((post) => [post.postId, profileMatches(post, profile)])),
    [posts, profile],
  )

  const renderPost = (post: OrganizerPost) => {
    const { event } = post
    const hits = matches.get(post.postId) ?? []
    const pinned = placementLabel(post)
    const registered = isCalendarRegistered(calendar[event.eventId])
    const isSaved = Boolean(saved[event.eventId])
    const partial = event.validationStatus === 'partial'
    return (
      <article
        key={post.postId}
        className={`row post${hits.length ? ' is-match' : ''}${pinned ? ' is-pinned' : ''}`}
      >
        <div className="row-main">
          <p className="post-eyebrow">
            <span>{originLabel(post)}</span>
            {post.organizerConfirmed && <span className="tag tag-confirmed">主催者確認済み</span>}
            {pinned && <span className="tag tag-pr">{pinned}</span>}
            {hits.length > 0 && <span className="tag tag-match">関心に合う: {hits.join('・')}</span>}
            <span className="post-date">{postedAtLabel(post.createdAt)}</span>
          </p>
          <div className="row-title">
            <button
              type="button"
              className="row-title-button"
              onClick={() => navigate(`/events/${encodeURIComponent(event.eventId)}`)}
            >
              {post.title}
            </button>
            {partial && <span className="tag">要確認</span>}
          </div>
          <p className="row-meta">
            {post.organizerName} · {placeLabel(event)} · {formatLocationType(event.location.type)} ·{' '}
            <a
              href={goUrl(event.eventId, post.origin === 'organizer' ? 'contact' : 'official')}
              target="_blank"
              rel="noopener noreferrer nofollow"
            >
              {hostOf(post.contactUrl)}
            </a>
          </p>
          <DualDateBlock event={event} />
          {excerpt(post.body) && <p className="post-body">{excerpt(post.body)}</p>}
          {post.origin === 'organizer' && post.linkedEventId && (
            <p className="fine">
              <Link to={`/events/${encodeURIComponent(post.linkedEventId)}`}>
                AI収集の一覧にも同じイベントがあります
              </Link>
            </p>
          )}
        </div>
        <div className="row-side">
          <span className="row-score" aria-hidden="true" />
          <div className="row-actions">
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
          <h1>主催者投稿</h1>
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
            最初の告知を投稿するか、毎朝の自動収集を待つと AI が集めたハッカソンがボット投稿として並びます。
          </p>
        ) : (
          posts.map(renderPost)
        ))}

      <CalendarSheet event={sheetEvent} onClose={() => setSheetEvent(null)} onConfirm={register} />
    </>
  )
}
