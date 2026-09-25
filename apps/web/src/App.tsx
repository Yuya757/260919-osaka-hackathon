/**
 * ルーティングとシェルのみ。画面の中身は screens/ にある。
 *
 * react-router を使うのは、スマホで Android の戻る操作と iOS のスワイプ戻りを
 * 成立させるため（画面設計書 §6.1）。useState での画面切り替えでは、戻る操作で
 * アプリごと離脱してしまう。
 */
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { AppStateProvider } from './state/AppState'
import { CalendarScreen } from './screens/CalendarScreen'
import { EventManageScreen } from './screens/EventManageScreen'
import { EventDetailScreen } from './screens/EventDetailScreen'
import { EventListScreen } from './screens/EventListScreen'
import { FeedScreen } from './screens/FeedScreen'
import { PostFormScreen } from './screens/PostFormScreen'
import { ProfileScreen } from './screens/ProfileScreen'
import { SettingsScreen } from './screens/SettingsScreen'
import { LoginScreen } from './screens/LoginScreen'
import { useSession } from './components/Avatar'

export default function App() {
  // ログイン（モック）するまでは中に入れない。利用者が替わったら状態を作り直す
  const session = useSession()
  if (!session) return <LoginScreen />
  return (
    <AppStateProvider key={session.userId} userId={session.userId}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<EventListScreen mode="home" />} />
            <Route path="saved" element={<EventListScreen mode="saved" />} />
            <Route path="feed" element={<FeedScreen />} />
            <Route path="feed/new" element={<PostFormScreen />} />
            <Route path="calendar" element={<CalendarScreen />} />
            <Route path="settings" element={<SettingsScreen />} />
            <Route path="settings/profile" element={<ProfileScreen />} />
            <Route path="events/:eventId" element={<EventDetailScreen />} />
            <Route path="events/:eventId/manage" element={<EventManageScreen />} />
            {/* 旧チャット画面。入力欄は一覧の最上部に統合した */}
            <Route path="agent" element={<Navigate to="/" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppStateProvider>
  )
}
