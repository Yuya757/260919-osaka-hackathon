import { useMemo, useState } from 'react'

type Filter = 'all' | 'soon' | 'online'

type EventItem = {
  id: string
  title: string
  organizer: string
  category: string
  location: string
  format: '会場' | 'オンライン' | 'ハイブリッド'
  deadline: string
  deadlineDay: string
  eventDate: string
  eventDay: string
  description: string
  match: number
  source: string
  urgent?: boolean
}

const events: EventItem[] = [
  {
    id: 'gemini-hack',
    title: 'Gemini API ハッカソン 2026',
    organizer: 'Google for Developers',
    category: '生成AI・ハッカソン',
    location: 'グランフロント大阪',
    format: '会場',
    deadline: '9月22日 23:59',
    deadlineDay: 'あと3日',
    eventDate: '10月11日 — 12日',
    eventDay: '22日後',
    description:
      'Gemini APIを使い、地域や暮らしの課題を解くプロトタイプを2日間で開発します。',
    match: 96,
    source: '公式サイトで確認済み',
    urgent: true,
  },
  {
    id: 'cloud-next',
    title: 'Cloud Builders Kansai',
    organizer: 'GDG Osaka',
    category: 'GCP・カンファレンス',
    location: '梅田スカイビル',
    format: 'ハイブリッド',
    deadline: '10月02日 18:00',
    deadlineDay: 'あと13日',
    eventDate: '10月18日',
    eventDay: '29日後',
    description:
      'Cloud Run、Vertex AI、データ基盤の実践事例を関西の開発者が共有する1dayイベントです。',
    match: 91,
    source: '公式サイトで確認済み',
  },
  {
    id: 'agent-meetup',
    title: 'AI Agent Product Meetup',
    organizer: 'Agentic Japan',
    category: 'AI Agent・ミートアップ',
    location: 'Google Meet',
    format: 'オンライン',
    deadline: '10月08日',
    deadlineDay: 'あと19日',
    eventDate: '10月09日 19:00',
    eventDay: '20日後',
    description:
      'プロダクトにAI Agentを組み込む設計、評価、運用の失敗と学びを持ち寄るオンライン勉強会です。',
    match: 88,
    source: '主催者ページで確認済み',
  },
]

function CalendarIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6.5 3v3M17.5 3v3M4 9h16M5.5 5h13A1.5 1.5 0 0 1 20 6.5v12a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-12A1.5 1.5 0 0 1 5.5 5Z" />
    </svg>
  )
}

function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2.8c.5 5.2 3.3 8 8.2 8.7-4.9.6-7.7 3.5-8.2 8.7-.5-5.2-3.3-8.1-8.2-8.7C8.7 10.8 11.5 8 12 2.8Z" />
    </svg>
  )
}

function PinIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z" />
      <circle cx="12" cy="10" r="2.25" />
    </svg>
  )
}

function App() {
  const [filter, setFilter] = useState<Filter>('all')
  const [synced, setSynced] = useState<Set<string>>(new Set())
  const [refreshing, setRefreshing] = useState(false)

  const visibleEvents = useMemo(() => {
    if (filter === 'soon') return events.filter((event) => event.urgent)
    if (filter === 'online')
      return events.filter((event) => event.format !== '会場')
    return events
  }, [filter])

  const refreshEvents = () => {
    setRefreshing(true)
    window.setTimeout(() => setRefreshing(false), 1100)
  }

  const toggleCalendar = (eventId: string) => {
    setSynced((current) => {
      const next = new Set(current)
      if (next.has(eventId)) next.delete(eventId)
      else next.add(eventId)
      return next
    })
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#" aria-label="超イベント管理 ホーム">
          <span className="brand-mark">〆</span>
          <span>
            超イベント
            <small>管理エージェント</small>
          </span>
        </a>

        <nav className="primary-nav" aria-label="メインナビゲーション">
          <a className="nav-item active" href="#">
            今日のイベント
          </a>
          <a className="nav-item" href="#">
            カレンダー
          </a>
          <a className="nav-item" href="#">
            保存したイベント
          </a>
        </nav>
      </header>

      <main>
        <header className="topbar">
          <div>
            <p className="today">2026年9月19日 土曜日</p>
            <h1>見逃したくない予定</h1>
          </div>
          <button
            className={`refresh-button ${refreshing ? 'refreshing' : ''}`}
            type="button"
            onClick={refreshEvents}
            disabled={refreshing}
          >
            <SparkIcon />
            {refreshing ? '探索しています…' : 'イベントを更新'}
          </button>
        </header>

        <section className="deadline-board" aria-labelledby="deadline-heading">
          <div className="deadline-copy">
            <p className="deadline-eyebrow">次の申込締切まで</p>
            <div className="countdown">
              <strong>03</strong>
              <span>日</span>
            </div>
            <p className="deadline-title" id="deadline-heading">
              Gemini API ハッカソン 2026
            </p>
          </div>

          <div className="date-rails" aria-label="締切日と開催日の時間差">
            <div className="rail deadline-rail">
              <span className="rail-label">申込締切</span>
              <time dateTime="2026-09-22T23:59:00+09:00">
                9/22 <small>火</small>
              </time>
            </div>
            <div className="rail event-rail">
              <span className="rail-label">イベント開催</span>
              <time dateTime="2026-10-11">
                10/11 <small>日</small>
              </time>
            </div>
            <span className="days-between">19日間の準備期間</span>
          </div>
        </section>

        <section className="event-section" aria-labelledby="event-heading">
          <div className="section-header">
            <div>
              <h2 id="event-heading">あなた向けのイベント</h2>
              <p>公式情報を確認済み · 関心に近い順</p>
            </div>
            <div className="filters" role="group" aria-label="イベント絞り込み">
              {[
                ['all', 'すべて'],
                ['soon', '締切間近'],
                ['online', 'オンライン可'],
              ].map(([value, label]) => (
                <button
                  key={value}
                  className={filter === value ? 'selected' : ''}
                  type="button"
                  aria-pressed={filter === value}
                  onClick={() => setFilter(value as Filter)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="event-list">
            {visibleEvents.map((event) => {
              const isSynced = synced.has(event.id)
              return (
                <article
                  className={`event-card ${event.urgent ? 'urgent' : ''}`}
                  key={event.id}
                >
                  <div className="event-score">
                    <span>{event.match}%</span>
                    <small>関心に一致</small>
                  </div>

                  <div className="event-body">
                    <div className="event-heading">
                      <div>
                        <div className="event-tags">
                          <span>{event.category}</span>
                          {event.urgent && <strong>締切間近</strong>}
                        </div>
                        <h3>{event.title}</h3>
                        <p className="organizer">{event.organizer}</p>
                      </div>
                      <button
                        className="bookmark"
                        type="button"
                        aria-label={`${event.title}を保存`}
                      >
                        ♡
                      </button>
                    </div>

                    <p className="description">{event.description}</p>

                    <div className="event-dates">
                      <div className="date-block deadline-date">
                        <span>申込締切</span>
                        <strong>{event.deadline}</strong>
                        <small>{event.deadlineDay}</small>
                      </div>
                      <span className="date-connector" aria-hidden="true" />
                      <div className="date-block event-date">
                        <span>イベント開催</span>
                        <strong>{event.eventDate}</strong>
                        <small>{event.eventDay}</small>
                      </div>
                    </div>

                    <div className="event-footer">
                      <div className="event-location">
                        <PinIcon />
                        <span>
                          {event.location}
                          <small>{event.format}</small>
                        </span>
                      </div>
                      <span className="verified">✓ {event.source}</span>
                      <button
                        className={isSynced ? 'calendar-button synced' : 'calendar-button'}
                        type="button"
                        onClick={() => toggleCalendar(event.id)}
                      >
                        <CalendarIcon />
                        {isSynced ? '登録済み' : '両方をカレンダーへ'}
                      </button>
                    </div>
                  </div>
                </article>
              )
            })}
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
