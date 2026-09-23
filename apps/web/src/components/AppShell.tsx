/**
 * 画面の外枠。上部に固定ヘッダ（ロゴ + 4つのナビ）、その下に本文。
 * 幅は 760px に収め、スマホでは横 20px の余白だけを残す。
 */
import { NavLink, Outlet } from 'react-router-dom'
import { AgentActivityPanel } from './AgentActivityPanel'

const NAV: [string, string][] = [
  ['/', 'ホーム'],
  ['/feed', 'フィード'],
  ['/calendar', 'カレンダー'],
  ['/saved', '保存'],
  ['/settings', '設定'],
]

export function AppShell() {
  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <span className="brand">
            {/* 360px では5項目が入らないので、狭い画面ではマークだけにする */}
            <img className="brand-mark" src="/favicon.svg" alt="" width={20} height={20} />
            <span className="brand-text">超イベント管理</span>
          </span>
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
        <AgentActivityPanel />
        <Outlet />
      </main>
    </div>
  )
}
