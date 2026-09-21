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
import { AgentChatScreen } from './screens/AgentChatScreen'
import { CalendarScreen } from './screens/CalendarScreen'
import { EventDetailScreen } from './screens/EventDetailScreen'
import { HomeScreen } from './screens/HomeScreen'
import { SavedScreen } from './screens/SavedScreen'
import { SettingsScreen } from './screens/SettingsScreen'

export default function App() {
  return (
    <AppStateProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<HomeScreen />} />
            <Route path="calendar" element={<CalendarScreen />} />
            <Route path="saved" element={<SavedScreen />} />
            <Route path="settings" element={<SettingsScreen />} />
            <Route path="agent" element={<AgentChatScreen />} />
            <Route path="events/:eventId" element={<EventDetailScreen />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppStateProvider>
  )
}
