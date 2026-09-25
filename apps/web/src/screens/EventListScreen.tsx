/**
 * S-01 ホーム / S-04 保存済み。
 *
 * 一覧の最上部にエージェントへの入力欄を置く。虫メガネで同じ文をエージェントに送る。
 * 左の「Web」を入れておくと、同じ文で Google 検索（ADR-014）もかける。専用のチャット画面は無い。
 */
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { daysUntil, isFinished, isUrgent, kindLabel, needsCheck } from '../lib/eventView'
import { EventCard } from '../components/EventCard'
import { CalendarSheet } from '../components/CalendarSheet'
import { SearchActivityPanel } from '../components/SearchActivityPanel'
import { WebSearchCard } from '../components/WebSearchCard'
import { GlobeIcon, SearchIcon } from '../components/Icon'
import { searchTheWeb } from '../api/client'
import type { Event, EventKind, WebSearchResponse } from '../types/api'

type Filter = 'all' | 'soon' | 'online' | 'check'

// 「すべて」はジャンルの行と共通の 1 つだけ。状態のチップは押し直すと外れる
const FILTERS: [Exclude<Filter, 'all'>, string][] = [
  ['soon', '締切間近'],
  ['online', 'オンライン'],
  ['check', '要確認'],
]

// ジャンルのチップは実際に集まっている種別だけを出す。空のチップを押させない
const KIND_ORDER: EventKind[] = [
  'hackathon',
  'contest',
  'meetup',
  'accelerator',
  'cocreation',
  'exhibition',
  'subsidy',
]

type Props = { mode: 'home' | 'saved' }

// 一度に描く行の数。数百件を一度に描くと開くのが遅くなるので、スクロールに合わせて足す
const PAGE_SIZE = 30

export function EventListScreen({ mode }: Props) {
  const {
    events,
    loadState,
    refreshing,
    loadError,
    saved,
    calendar,
    calendarCounts,
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
  const [shownCount, setShownCount] = useState(PAGE_SIZE)
  // 利用者ごとの Web 検索（ADR-014）。結果は画面のメモリにだけ持つ
  const [web, setWeb] = useState<{
    result: WebSearchResponse | null
    pending: boolean
    error: string | null
  }>({ result: null, pending: false, error: null })
  const webSession = useRef<string | undefined>(undefined)
  // Web 検索は既定で切っておく。検索グラウンディングは 1 回ごとに費用がかかる
  const [webOn, setWebOn] = useState(false)

  const onWebSearch = async () => {
    const text = query.trim()
    if (!text || web.pending) return
    setWeb({ result: null, pending: true, error: null })
    try {
      const result = await searchTheWeb(text, webSession.current)
      webSession.current = result.sessionId
      setWeb({ result, pending: false, error: null })
    } catch (caught) {
      setWeb({
        result: null,
        pending: false,
        error: caught instanceof Error ? caught.message : 'Web 検索に失敗しました。',
      })
    }
  }
  const moreRef = useRef<HTMLDivElement>(null)

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

  // 探索の結果はエージェントが種別まで絞ったもの。チップを押したままだと
  // 二重に絞ることになるので、新しい結果が来たらチップは「すべて」へ戻す
  useEffect(() => {
    if (agentReply) setKind('all')
  }, [agentReply])

  const visible = useMemo(() => {
    // 問いかけの解釈と絞り込みはプール探索エージェントが行う。ここではチップだけ
    let pool = upcoming
    if (kind !== 'all' && kinds.includes(kind)) pool = pool.filter((event) => event.kind === kind)
    if (filter === 'soon') pool = pool.filter((event) => isUrgent(event))
    if (filter === 'online') pool = pool.filter((event) => event.location.type !== 'offline')
    if (filter === 'check') pool = pool.filter(needsCheck)
    return pool
  }, [upcoming, filter, kind, kinds])

  // 絞り込みが変わったら先頭から描き直す
  useEffect(() => {
    setShownCount(PAGE_SIZE)
  }, [visible])

  // 最後の行が見えてきたら次の分を描く
  useEffect(() => {
    const sentinel = moreRef.current
    if (!sentinel || shownCount >= visible.length) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShownCount((count) => count + PAGE_SIZE)
        }
      },
      { rootMargin: '600px 0px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [shownCount, visible.length])

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
    if (webOn) void onWebSearch()
  }

  return (
    <>
      <div className="list-head">
        {/* 保存済みは自分で選んだイベントを見返す画面。探索の入力欄は要らない */}
        {mode === 'home' && (
          <form className="ask" onSubmit={onAsk}>
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
            {/* 入れておくと、収集済みの一覧とは別に Google 検索でも Web を調べる。結果は本人にだけ出し、保存しない */}
            <button
              type="button"
              className={`ask-web${webOn ? ' is-on' : ''}`}
              aria-pressed={webOn}
              title={webOn ? 'Web 検索: オン' : 'Web 検索: オフ'}
              onClick={() => setWebOn((on) => !on)}
            >
              <GlobeIcon className="ask-icon" />
              <span>Web</span>
            </button>
            <button
              type="submit"
              className={`ask-submit${agentPending ? ' is-busy' : ''}`}
              disabled={agentPending || (webOn && web.pending)}
              aria-label={agentPending ? '探索中' : webOn ? '一覧と Web を探す' : '探す'}
              title="探す"
            >
              {agentPending ? (
                <span className="spinner spinner-sm" aria-hidden="true" />
              ) : (
                <SearchIcon className="ask-icon" />
              )}
            </button>
          </form>
        )}

        {mode === 'home' && (
          <WebSearchCard
            result={web.result}
            pending={web.pending}
            error={web.error}
            onClose={() => setWeb({ result: null, pending: false, error: null })}
          />
        )}

        {/* ジャンルと状態を 1 行にまとめる。「すべて」は両方の絞り込みを外す */}
        <div className="filters" role="group" aria-label="イベントの絞り込み">
          <button
            type="button"
            aria-pressed={kind === 'all' && filter === 'all'}
            onClick={() => {
              setKind('all')
              setFilter('all')
            }}
          >
            すべて
          </button>
          {kinds.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={kind === value}
              onClick={() => setKind(kind === value ? 'all' : value)}
            >
              {kindLabel(value)}
            </button>
          ))}
          <span className="filters-divider" aria-hidden="true" />
          {FILTERS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              onClick={() => setFilter(filter === value ? 'all' : value)}
            >
              {label}
            </button>
          ))}
        </div>

        {mode === 'home' && (agentReply || agentPending) && (
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
          {/* 前回分を出したまま取り直しているあいだ */}
          {refreshing && loadState === 'ready' && (
            <span className="refreshing">
              <span className="spinner spinner-sm" aria-hidden="true" /> 最新に更新中
            </span>
          )}
        </p>
      )}

      {/* 前回の一覧を出したまま最新を取れなかった。古い一覧を黙って出さない（ADR-005） */}
      {loadState === 'ready' && loadError && (
        <div className="stale-warning" role="alert">
          <p>
            最新の一覧を取得できませんでした。表示しているのは前回取得した一覧です。
            申込前に公式サイトで締切をご確認ください。
          </p>
          <button type="button" className="button" onClick={() => void refresh()}>
            再試行
          </button>
        </div>
      )}

      {loadState === 'loading' && (
        <div aria-busy="true">
          <p className="loading-line">
            <span className="spinner" aria-hidden="true" />
            <span className="shimmer">収集済みのイベントを読み込んでいます</span>
          </p>
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
            ) : mode === 'saved' ? (
              <>条件に合う保存済みのイベントはありません。</>
            ) : (
              <>
                条件に合うイベントはありません。
                <br />
                上の入力欄に問いかけると、収集済みのイベントから探し直します。
              </>
            )}
          </p>
        ) : (
          // 探索中は薄くし、結果が届いたら上の行から順に出す（key で描き直す）
          <div
            key={mode === 'home' ? agentReply?.text || 'pool' : 'saved'}
            className={[
              'list-rows',
              mode === 'home' && agentPending ? 'is-agent-working' : '',
              mode === 'home' && agentReply?.text && !agentPending ? 'is-fresh' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            aria-busy={mode === 'home' && agentPending}
          >
            {visible.slice(0, shownCount).map((event) => (
              <EventCard
                key={event.eventId}
                event={event}
                saved={Boolean(saved[event.eventId])}
                calendar={calendar[event.eventId]}
                calendarCount={calendarCounts[event.eventId] ?? 0}
                onToggleSaved={toggleSaved}
                onOpenCalendar={setSheetEvent}
              />
            ))}
          </div>
        ))}

      {loadState === 'ready' && shownCount < visible.length && (
        <div ref={moreRef} className="list-more" aria-hidden="true">
          <span className="spinner spinner-sm" />
        </div>
      )}

      <CalendarSheet event={sheetEvent} onClose={() => setSheetEvent(null)} onConfirm={register} />
    </>
  )
}
