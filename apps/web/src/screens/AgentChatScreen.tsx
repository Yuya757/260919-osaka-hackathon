/** S-06 エージェントチャット（全画面シート） */
import { useNavigate } from 'react-router-dom'
import { AgentChat } from '../components/AgentChat'
import { CloseIcon } from '../components/Icon'

export function AgentChatScreen() {
  const navigate = useNavigate()
  return (
    <>
      <header className="app-header">
        <div className="header-main">
          <p className="header-eyebrow">エージェント</p>
          <h1 className="header-compact">関心を伝えて探索</h1>
        </div>
        <button type="button" className="icon-button" aria-label="閉じる" onClick={() => navigate('/')}>
          <CloseIcon />
        </button>
      </header>
      <AgentChat />
    </>
  )
}
