import { useEffect, useRef, useState, type FormEvent } from 'react'
import { pollAgentRun, listEvents, sendChat, startAgentRun } from '../api/client'
import type { ApiEvent, ChatAction } from '../types/api'

type ChatMessage = {
  id: string
  role: 'user' | 'agent' | 'system'
  text: string
}

type AgentChatProps = {
  onEventsUpdated: (events: ApiEvent[]) => void
  onRunStateChange?: (busy: boolean) => void
}

const SUGGESTIONS = [
  '関西の生成AIハッカソンを探して',
  'オンラインのミートアップも入れて',
  'イベントを更新して',
]

export function AgentChat({ onEventsUpdated, onRunStateChange }: AgentChatProps) {
  const [sessionId, setSessionId] = useState<string | undefined>()
  const [input, setInput] = useState('')
  const [pending, setPending] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'agent',
      text: '関心分野や地域を教えてください。申込締切と開催日を分けて探します。',
    },
  ])
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, pending])

  const append = (message: ChatMessage) => {
    setMessages((current) => [...current, message])
  }

  const handleActions = async (actions: ChatAction[] | undefined) => {
    if (!actions?.length) return

    for (const action of actions) {
      if (action.type === 'agent_run_started') {
        onRunStateChange?.(true)
        append({
          id: crypto.randomUUID(),
          role: 'system',
          text: 'イベント探索を開始しました…',
        })
        let lastStep = ''
        const run = await pollAgentRun(action.runId, (progress) => {
          if (progress.currentStep && progress.currentStep !== lastStep) {
            lastStep = progress.currentStep
            append({
              id: crypto.randomUUID(),
              role: 'system',
              text: `進行中: ${progress.currentStep}`,
            })
          }
        })
        const result = await listEvents(run.runId)
        onEventsUpdated(result.events)
        onRunStateChange?.(false)
        append({
          id: crypto.randomUUID(),
          role: 'agent',
          text:
            run.status === 'failed'
              ? run.errorMessage || '探索に失敗しました。もう一度試してください。'
              : `${result.events.length}件のイベントを更新しました。右側の一覧を確認してください。`,
        })
      }

      if (action.type === 'events_ready') {
        const result = await listEvents()
        onEventsUpdated(result.events)
      }
    }
  }

  const submitMessage = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || pending) return

    setPending(true)
    append({ id: crypto.randomUUID(), role: 'user', text: trimmed })
    setInput('')

    try {
      const response = await sendChat({ sessionId, message: trimmed })
      setSessionId(response.sessionId)
      append({
        id: crypto.randomUUID(),
        role: 'agent',
        text: response.reply,
      })
      await handleActions(response.actions)
    } catch (error) {
      append({
        id: crypto.randomUUID(),
        role: 'agent',
        text:
          error instanceof Error
            ? `接続に失敗しました: ${error.message}`
            : 'エージェントに接続できませんでした。',
      })
    } finally {
      setPending(false)
      onRunStateChange?.(false)
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    void submitMessage(input)
  }

  const triggerRefresh = async () => {
    if (pending) return
    setPending(true)
    onRunStateChange?.(true)
    try {
      const run = await startAgentRun(true)
      await handleActions([{ type: 'agent_run_started', runId: run.runId }])
    } catch (error) {
      append({
        id: crypto.randomUUID(),
        role: 'agent',
        text:
          error instanceof Error
            ? `更新に失敗しました: ${error.message}`
            : '更新に失敗しました。',
      })
    } finally {
      setPending(false)
      onRunStateChange?.(false)
    }
  }

  return (
    <section className="agent-chat" aria-label="エージェントチャット">
      <header className="agent-chat-header">
        <div>
          <p>エージェント</p>
          <strong>関心を伝えて探索</strong>
        </div>
        <button type="button" className="chat-refresh" onClick={() => void triggerRefresh()} disabled={pending}>
          更新
        </button>
      </header>

      <div className="chat-suggestions" aria-label="候補プロンプト">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            disabled={pending}
            onClick={() => void submitMessage(suggestion)}
          >
            {suggestion}
          </button>
        ))}
      </div>

      <div className="chat-messages" ref={listRef}>
        {messages.map((message) => (
          <div key={message.id} className={`chat-bubble ${message.role}`}>
            {message.text}
          </div>
        ))}
        {pending && <div className="chat-bubble system">応答を待っています…</div>}
      </div>

      <form className="chat-composer" onSubmit={onSubmit}>
        <label className="sr-only" htmlFor="agent-chat-input">
          エージェントへのメッセージ
        </label>
        <textarea
          id="agent-chat-input"
          value={input}
          rows={2}
          placeholder="例: 大阪のGCPハッカソンを探して"
          disabled={pending}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void submitMessage(input)
            }
          }}
        />
        <button type="submit" disabled={pending || !input.trim()}>
          送信
        </button>
      </form>
    </section>
  )
}
