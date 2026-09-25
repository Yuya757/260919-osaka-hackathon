/**
 * 画面の外枠。上部に固定ヘッダ（ロゴ + 5つのナビ）、その下に本文。
 * 幅は 760px に収め、スマホでは横 20px の余白だけを残す。
 * ナビはアイコン付き。スマホでは画面の下にタブとして並べ、指で押しやすくする。
 */
import type { ComponentType } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { Avatar, useAccount } from './Avatar'
import { AgentActivityPanel } from './AgentActivityPanel'
import { BookmarkIcon, CalendarIcon, FeedIcon, HomeIcon, SettingsIcon } from './Icon'

const NAV: [string, string, ComponentType<{ className?: string }>][] = [
  ['/', 'ホーム', HomeIcon],
  ['/feed', 'フィード', FeedIcon],
  ['/calendar', 'カレンダー', CalendarIcon],
  ['/saved', '保存', BookmarkIcon],
  ['/settings', '設定', SettingsIcon],
]

export function AppShell() {
  const account = useAccount()
  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <span className="brand">
            <img className="brand-mark" src="/favicon.svg" alt="" width={24} height={24} />
            <span className="brand-text">超イベント管理</span>
          </span>
          <nav className="topnav" aria-label="メインナビゲーション">
            {NAV.map(([to, label, NavIcon]) => (
              <NavLink key={to} to={to} end={to === '/'}>
                <NavIcon className="nav-icon" />
                <span className="nav-label">{label}</span>
              </NavLink>
            ))}
          </nav>
          <Link
            to="/settings"
            className="topbar-account"
            aria-label={account.name ? `${account.name}のプロフィール` : 'プロフィールを設定'}
            title={account.name || 'プロフィールを設定'}
          >
            <Avatar account={account} />
          </Link>
        </div>
      </header>
      <main className="page">
        <AgentActivityPanel />
        <Outlet />
      </main>
    </div>
  )
}
