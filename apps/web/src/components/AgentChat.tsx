/**
 * S-06 エージェントチャットの本体。
 *
 * Runの開始と進捗は AppState が持つ。ここで独自にポーリングすると、
 * 全タブ共通の進捗バナーと二重にポーリングして状態がずれるため。
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { sendChat } from '../api/client'
import { useAppState } from '../state/AppState'
import { isRunning, RUN_STEPS } from '../lib/runSteps'
import type { ChatAction } from '../types/api'

type ChatMessage = {
  id: string
  role: 'user' | 'agent' | 'system'
  text: string
  /** Grounding由来の応答に付く、Googleが返す表示用HTML（§6.4） */
  searchSuggestionsHtml?: string | null
}

const SUGGESTIONS = [
  '関西の生成AIハッカソンを探して',
  'オンラインのミートアップも入れて',
  'イベントを更新して',
]

function newId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : String(Math.random())
}

export function AgentChat() {
  const { run, startRun, refresh } = useAppState()
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
  }, [messages, pending, run?.currentStep])

  const append = (message: ChatMessage) => setMessages((current) => [...current, message])

  const handleActions = async (actions: ChatAction[] | undefined) => {
    if (!actions?.length) return
    for (const action of actions) {
      if (action.type === 'agent_run_started') {
        append({ id: newId(), role: 'system', text: 'イベント探索を開始しました。' })
        await startRun()
        append({
          id: newId(),
          role: 'agent',
          // スマホには「右側の一覧」は存在しない
          text: 'ホームのタブで結果を確認できます。',
        })
      }
      if (action.type === 'events_ready') {
        await refresh()
      }
    }
  }

  const submitMessage = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || pending) return
    setPending(true)
    append({ id: newId(), role: 'user', text: trimmed })
    setInput('')
    try {
      const response = await sendChat({ sessionId, message: trimmed })
      setSessionId(response.sessionId)
      append({
        id: newId(),
        role: 'agent',
        text: response.reply,
        searchSuggestionsHtml: response.searchSuggestionsHtml,
      })
      await handleActions(response.actions)
    } catch (error) {
      append({
        id: newId(),
        role: 'agent',
        text:
          error instanceof Error
            ? `接続に失敗しました: ${error.message}`
            : 'エージェントに接続できませんでした。',
      })
    } finally {
      setPending(false)
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    void submitMessage(input)
  }

  const running = isRunning(run?.status)
  const currentIndex = RUN_STEPS.findIndex((step) => step.id === run?.currentStep)

  return (
    <div className="chat">
      {running && (
        <ol className="step-list" aria-label="探索の進捗">
          {RUN_STEPS.map((step, index) => {
            const state =
              currentIndex < 0
                ? 'todo'
                : index < currentIndex
                  ? 'done'
                  : index === currentIndex
                    ? 'now'
                    : 'todo'
            return (
              <li key={step.id} className={`step is-${state}`}>
                <span aria-hidden="true">{state === 'done' ? '✓' : state === 'now' ? '◍' : '○'}</span>
                {step.label}
              </li>
            )
          })}
        </ol>
      )}

      <div className="chat-messages" ref={listRef}>
        {messages.map((message) => (
          <div key={message.id}>
            <div className={`bubble is-${message.role}`}>{message.text}</div>
            {message.role === 'agent' && (
              /*
               * Search Suggestions の表示位置（§3.7 / §6.4）。
               * Googleが返すHTMLは無改変で描画する義務がある。再スタイル・
               * 切り抜き・折りたたみ・非表示は禁止。未提供のあいだは枠だけ
               * 確保しておき、後から差し込んでもレイアウトが跳ねないようにする。
               */
              <div className="search-suggestions">
                {message.searchSuggestionsHtml ? (
                  <div
                    // eslint-disable-next-line react/no-danger
                    dangerouslySetInnerHTML={{ __html: message.searchSuggestionsHtml }}
                  />
                ) : (
                  <span className="fine">
                    Search Suggestions 表示位置（Grounding応答時にGoogle提供のHTMLを挿入）
                  </span>
                )}
              </div>
            )}
          </div>
        ))}
        {pending && <div className="bubble is-system">応答を待っています…</div>}
      </div>

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

      <form className="chat-composer" onSubmit={onSubmit}>
        <label className="sr-only" htmlFor="agent-chat-input">
          エージェントへのメッセージ
        </label>
        <textarea
          id="agent-chat-input"
          value={input}
          rows={1}
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
    </div>
  )
}
