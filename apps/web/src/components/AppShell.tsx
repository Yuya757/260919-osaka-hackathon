/**
 * 画面の外枠。
 * タブバーは sticky。PCで中央420pxに収めたときも同じ規則で収まる（§5.3）。
 */
import { Outlet, useLocation } from 'react-router-dom'
import { TabBar } from './TabBar'

export function AppShell() {
  const { pathname } = useLocation()
  // 詳細とチャットはタブではないので、タブバーを出さない
  const hideTabs = pathname.startsWith('/events/') || pathname.startsWith('/agent')

  return (
    <div className="app">
      <Outlet />
      {!hideTabs && <TabBar />}
    </div>
  )
}
