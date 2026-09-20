import { useMemo, useState } from 'react'
import { ProfileDialog } from './ProfileDialog'
import { EventCalendarCard } from './EventCalendarCard'
import { loadProfile, profileStorageKey } from './profile'
import type { Profile } from './profile'

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
  const [activePage, setActivePage] = useState<'today' | 'calendar'>('today')
  const [initialProfile] = useState(loadProfile)
  const [profile, setProfile] = useState(initialProfile.profile)
  const [profileOpen, setProfileOpen] = useState(false)
  const [persisted, setPersisted] = useState(initialProfile.profile !== null)
  const [profileNotice, setProfileNotice] = useState(initialProfile.notice)

  const saveProfile = (value: Profile, remember: boolean): string | null => {
    try {
      if (remember) localStorage.setItem(profileStorageKey, JSON.stringify(value))
      else localStorage.removeItem(profileStorageKey)
    } catch {
      // 既存の保存内容が残る場合は、保存解除に成功したと表示しない。
      if (remember || persisted) return 'ブラウザの保存設定を変更できませんでした。設定を確認して再度お試しください。'
    }
    setProfile(value)
    setPersisted(remember)
    setProfileNotice(remember ? 'プロフィールをこのブラウザに保存しました。' : 'プロフィールを登録しました。再読み込みすると内容は消えます。')
    setProfileOpen(false)
    return null
  }
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
      <aside className="sidebar">
        <a className="brand" href="#" aria-label="超イベント管理 ホーム" onClick={(event) => { event.preventDefault(); setActivePage('today') }}>
          <span className="brand-mark">〆</span>
          <span>
            超イベント
            <small>管理エージェント</small>
          </span>
        </a>

        <nav className="primary-nav" aria-label="メインナビゲーション">
          <button
            className={`nav-item${activePage === 'today' ? ' active' : ''}`}
            type="button"
            aria-current={activePage === 'today' ? 'page' : undefined}
            aria-controls="today-page"
            onClick={() => setActivePage('today')}
          >
            <span>⌂</span>今日のイベント
          </button>
          <button
            className={`nav-item${activePage === 'calendar' ? ' active' : ''}`}
            type="button"
            aria-current={activePage === 'calendar' ? 'page' : undefined}
            aria-controls="calendar-page"
            onClick={() => setActivePage('calendar')}
          >
            <span>▦</span>カレンダー
          </button>
          <a className="nav-item" href="#">
            <span>♡</span>保存したイベント
          </a>
        </nav>

        <div className="agent-note">
          <SparkIcon />
          <p>
            次回の自動探索
            <strong>明日 7:00</strong>
          </p>
        </div>

        <button className="profile" type="button" aria-label="プロフィールを登録・編集" aria-haspopup="dialog" onClick={() => setProfileOpen(true)}>
          <span className="avatar">YK</span>
          <span>
            Yuya Kaneko
            <small>{profile ? [profile.prefecture, ...profile.genres].join('・') : 'プロフィール未登録'}</small>
          </span>
          <span aria-hidden="true">•••</span>
        </button>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <p className="today">2026年9月19日 土曜日</p>
            <h1>{activePage === 'calendar' ? 'カレンダー' : '見逃したくない予定'}</h1>
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

        {!profile && <div className="profile-registration"><span>参加しやすい場所と興味を登録しましょう。</span><button type="button" onClick={() => setProfileOpen(true)}>プロフィール新規登録</button></div>}
        <p className="profile-notice" role="status">{profileNotice}</p>

        <div id="today-page" hidden={activePage !== 'today'}>
        <section className="deadline-board" aria-labelledby="deadline-heading">
          <div className="deadline-copy">
            <p>次の申込締切まで</p>
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
              <span className="rail-line" />
              <time dateTime="2026-09-22T23:59:00+09:00">
                9/22 <small>火</small>
              </time>
            </div>
            <div className="rail event-rail">
              <span className="rail-label">イベント開催</span>
              <span className="rail-line" />
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
              <p>AIが公式情報を確認し、関心との近さで並べています。</p>
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
                        <span><span aria-hidden="true">🚨</span> 申込期限</span>
                        <strong>{event.deadline}</strong>
                        <small>{event.deadlineDay}</small>
                      </div>
                      <span className="date-connector" aria-hidden="true" />
                      <div className="date-block event-date">
                        <span><span aria-hidden="true">📅</span> 実施日</span>
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
        </div>

        {/* 非表示でも保持し、メニューの往復でデモの登録状態が消えないようにする。 */}
        <section id="calendar-page" hidden={activePage !== 'calendar'} aria-labelledby="calendar-heading">
          <div className="section-header">
            <div>
              <h2 id="calendar-heading">イベントのカレンダー登録</h2>
              <p>申込締切と本番日程を選んで登録できます。現在はデモ表示です。</p>
            </div>
          </div>
          <div className="event-list">
            {events.map(event => <EventCalendarCard key={event.id} event={event} />)}
          </div>
        </section>
      </main>
      {profileOpen && <ProfileDialog profile={profile} persisted={persisted} onClose={() => setProfileOpen(false)} onSave={saveProfile} />}
    </div>
  )
}

export default App
