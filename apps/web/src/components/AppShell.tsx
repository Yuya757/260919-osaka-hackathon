/**
 * 画面の外枠。上部に固定ヘッダ（ロゴ + 4つのナビ）、その下に本文。
 * 幅は 760px に収め、スマホでは横 20px の余白だけを残す。
 */
import { NavLink, Outlet } from 'react-router-dom'
import { RunProgressBanner } from './RunProgressBanner'

const NAV: [string, string][] = [
  ['/', 'ホーム'],
  ['/calendar', 'カレンダー'],
  ['/saved', '保存'],
  ['/settings', '設定'],
]

export function AppShell() {
  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <span className="brand">超イベント管理</span>
          <nav className="topnav" aria-label="メインナビゲーション">
            {NAV.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === '/'}>
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="page">
        <RunProgressBanner />
        <Outlet />
      </main>
    </div>
  )
}
