/**
 * S-01 ホーム / S-04 保存済み。
 *
 * 一覧の最上部にエージェントへの入力欄を置く。文字を打つとその場で一覧が
 * 絞り込まれ、「探す」で同じ文をエージェントに送る。専用のチャット画面は無い。
 */
import { useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import {
  categoryLabel,
  daysUntil,
  formatLocationType,
  isFinished,
  isUrgent,
  placeLabel,
} from '../lib/eventView'
import { isRunning } from '../lib/runSteps'
import { EventCard } from '../components/EventCard'
import { CalendarSheet } from '../components/CalendarSheet'
import type { Event } from '../types/api'

type Filter = 'all' | 'soon' | 'online' | 'check'

const FILTERS: [Filter, string][] = [
  ['all', 'すべて'],
  ['soon', '締切間近'],
  ['online', 'オンライン'],
  ['check', '要確認'],
]

/** 入力欄の語をすべて含むイベントだけ残す。表示している文字列に対して照合する。 */
function matches(event: Event, query: string): boolean {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return true
  const hay = [
    event.title,
    categoryLabel(event.category),
    event.organizer ?? '',
    placeLabel(event),
    formatLocationType(event.location.type),
    event.summary,
  ]
    .join(' ')
    .toLowerCase()
  return terms.every((term) => hay.includes(term))
}

type Props = { mode: 'home' | 'saved' }

export function EventListScreen({ mode }: Props) {
  const {
    events,
    loadState,
    loadError,
    run,
    saved,
    calendar,
    query,
    setQuery,
    agentReply,
    agentPending,
    ask,
    toggleSaved,
    register,
    refresh,
  } = useAppState()
  const [filter, setFilter] = useState<Filter>('all')
  const [sheetEvent, setSheetEvent] = useState<Event | null>(null)
  const navigate = useNavigate()
  const busy = isRunning(run?.status)

  const upcoming = useMemo(() => {
    const open = events.filter((event) => !isFinished(event))
    return mode === 'saved' ? open.filter((event) => saved[event.eventId]) : open
  }, [events, mode, saved])

  const visible = useMemo(() => {
    let pool = upcoming.filter((event) => matches(event, query))
    if (filter === 'soon') pool = pool.filter((event) => isUrgent(event))
    if (filter === 'online') pool = pool.filter((event) => event.location.type !== 'offline')
    if (filter === 'check') pool = pool.filter((event) => event.validationStatus === 'partial')
    return pool
  }, [upcoming, query, filter])

  // 締切が確認できているものの中で、いちばん近いもの。不明な締切は候補にしない
  const nextDeadline = useMemo(() => {
    return upcoming
      .filter((event) => (daysUntil(event.dates.applicationDeadline, event.dates.timezone) ?? -1) >= 0)
      .sort(
        (a, b) =>
          (daysUntil(a.dates.applicationDeadline, a.dates.timezone) ?? 0) -
          (daysUntil(b.dates.applicationDeadline, b.dates.timezone) ?? 0),
      )[0]
  }, [upcoming])
  const nextDays = nextDeadline
    ? daysUntil(nextDeadline.dates.applicationDeadline, nextDeadline.dates.timezone)
    : null

  const onAsk = (event: FormEvent) => {
    event.preventDefault()
    void ask(query)
  }

  return (
    <>
      <div className="list-head">
        <form className="ask" onSubmit={onAsk}>
          <span className="ask-mark" aria-hidden="true">
            ›
          </span>
          <label className="sr-only" htmlFor="ask-input">
            条件やエージェントへの問いかけ
          </label>
          <input
            id="ask-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="条件で絞り込み・探す（例：大阪 生成AI）"
            autoComplete="off"
          />
          <button type="submit" disabled={agentPending || busy}>
            {agentPending || busy ? '探索中…' : '探す'}
          </button>
        </form>

        <div className="filters" role="group" aria-label="イベントの絞り込み">
          {FILTERS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>

        {agentReply && (
          <div className="agent-line" role="status">
            <p>{agentReply.text}</p>
            {/*
             * Search Suggestions（§3.7 / §6.4）。Grounding 由来の生成文を出す
             * 唯一の場所なので、Googleが返すHTMLを無改変で直下に描画する。
             * 再スタイル・切り抜き・折りたたみ・非表示は禁止。
             */}
            <div className="search-suggestions">
              {agentReply.searchSuggestionsHtml ? (
                <div
                  // eslint-disable-next-line react/no-danger
                  dangerouslySetInnerHTML={{ __html: agentReply.searchSuggestionsHtml }}
                />
              ) : (
                <span className="fine">
                  Search Suggestions 表示位置（Grounding応答時にGoogle提供のHTMLを挿入）
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="next-line">
        <span className="dot dot-deadline" aria-hidden="true" />
        <span className="next-label">次の締切</span>
        <strong>{nextDays === null ? '—' : nextDays === 0 ? '今日' : `あと${nextDays}日`}</strong>
        {nextDeadline ? (
          <button
            type="button"
            className="next-title"
            onClick={() => navigate(`/events/${encodeURIComponent(nextDeadline.eventId)}`)}
          >
            {nextDeadline.title}
          </button>
        ) : (
          <span className="next-title" />
        )}
        <span className="next-count">
          {visible.length} / {upcoming.length}件
        </span>
      </div>

      {loadState === 'loading' && (
        <div aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div className="skeleton-row" key={i} aria-hidden="true" />
          ))}
        </div>
      )}

      {loadState === 'error' && (
        <div className="empty">
          <p>
            <strong>イベントを取得できませんでした</strong>
            <br />
            {loadError}
          </p>
          <button type="button" className="button" onClick={() => void refresh()}>
            再試行
          </button>
        </div>
      )}

      {loadState === 'ready' &&
        (visible.length === 0 ? (
          <p className="empty">
            {mode === 'saved' && upcoming.length === 0 ? (
              <>
                保存したイベントはありません。
                <br />
                一覧の「保存」を押すと、ここに集まります。
              </>
            ) : (
              <>
                条件に合うイベントはありません。
                <br />
                上の入力欄に関心を書くと、エージェントが探し直します。
              </>
            )}
          </p>
        ) : (
          visible.map((event) => (
            <EventCard
              key={event.eventId}
              event={event}
              saved={Boolean(saved[event.eventId])}
              calendar={calendar[event.eventId]}
              onToggleSaved={toggleSaved}
              onOpenCalendar={setSheetEvent}
            />
          ))
        ))}

      <CalendarSheet event={sheetEvent} onClose={() => setSheetEvent(null)} onConfirm={register} />
    </>
  )
}
