/**
 * S-01 ホーム / S-04 保存済み。
 *
 * 一覧の最上部にエージェントへの入力欄を置く。文字を打つとその場で一覧が
 * 絞り込まれ、「探す」で同じ文をエージェントに送る。専用のチャット画面は無い。
 */
import { useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { daysUntil, isFinished, isUrgent, kindLabel } from '../lib/eventView'
import { EventCard } from '../components/EventCard'
import { CalendarSheet } from '../components/CalendarSheet'
import { SearchActivityPanel } from '../components/SearchActivityPanel'
import type { Event, EventKind } from '../types/api'

type Filter = 'all' | 'soon' | 'online' | 'check'

const FILTERS: [Filter, string][] = [
  ['all', 'すべて'],
  ['soon', '締切間近'],
  ['online', 'オンライン'],
  ['check', '要確認'],
]

// ジャンルのチップは実際に集まっている種別だけを出す。空のチップを押させない
const KIND_ORDER: EventKind[] = [
  'hackathon',
  'contest',
  'accelerator',
  'cocreation',
  'exhibition',
  'subsidy',
]

type Props = { mode: 'home' | 'saved' }

export function EventListScreen({ mode }: Props) {
  const {
    events,
    loadState,
    loadError,
    saved,
    calendar,
    query,
    setQuery,
    agentReply,
    agentPending,
    ask,
    lastCollectedAt,
    toggleSaved,
    register,
    refresh,
  } = useAppState()
  const [filter, setFilter] = useState<Filter>('all')
  const [kind, setKind] = useState<EventKind | 'all'>('all')
  const [sheetEvent, setSheetEvent] = useState<Event | null>(null)
  const navigate = useNavigate()

  const upcoming = useMemo(() => {
    const open = events.filter((event) => !isFinished(event))
    return mode === 'saved' ? open.filter((event) => saved[event.eventId]) : open
  }, [events, mode, saved])

  // 2 種類以上あるときだけジャンルの行を出す。ハッカソンだけなら意味が無い
  const kinds = useMemo(() => {
    const present = new Set(upcoming.map((event) => event.kind))
    const ordered = KIND_ORDER.filter((value) => present.has(value))
    return ordered.length > 1 ? ordered : []
  }, [upcoming])

  const visible = useMemo(() => {
    // 問いかけの解釈と絞り込みはプール探索エージェントが行う。ここではチップだけ
    let pool = upcoming
    if (kind !== 'all' && kinds.includes(kind)) pool = pool.filter((event) => event.kind === kind)
    if (filter === 'soon') pool = pool.filter((event) => isUrgent(event))
    if (filter === 'online') pool = pool.filter((event) => event.location.type !== 'offline')
    if (filter === 'check') pool = pool.filter((event) => event.validationStatus === 'partial')
    return pool
  }, [upcoming, filter, kind, kinds])

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
            placeholder="どんなイベント？（例：京都で来月 学生向け 生成AI）"
            autoComplete="off"
          />
          <button type="submit" disabled={agentPending}>
            {agentPending ? '探索中…' : '探す'}
          </button>
        </form>

        {kinds.length > 0 && (
          <div className="filters" role="group" aria-label="ジャンルの絞り込み">
            <button type="button" aria-pressed={kind === 'all'} onClick={() => setKind('all')}>
              すべて
            </button>
            {kinds.map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={kind === value}
                onClick={() => setKind(value)}
              >
                {kindLabel(value)}
              </button>
            ))}
          </div>
        )}

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

        {(agentReply || agentPending) && (
          <SearchActivityPanel
            reply={agentReply?.text ?? ''}
            activity={agentReply?.activity ?? []}
            pending={agentPending}
          />
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
      {lastCollectedAt && (
        <p className="fine collected-at">
          最終収集:{' '}
          {new Date(lastCollectedAt).toLocaleString('ja-JP', {
            timeZone: 'Asia/Tokyo',
            month: 'numeric',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
          })}
          {mode === 'home' && ' · 毎朝7時に自動収集'}
        </p>
      )}

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
                上の入力欄に問いかけると、収集済みのイベントから探し直します。
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
