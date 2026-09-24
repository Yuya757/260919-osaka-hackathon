/**
 * プール探索エージェントの動き（ADR-010）。
 * 解釈 → 絞り込み → 採点 → 提示 の4役割。Web には出ないので数秒で終わり、
 * 完了した状態を「何をしたか」として、動きの行を時系列で見せる。
 */
import { useEffect, useState } from 'react'
import type { SearchActivity, SearchAgent } from '../types/api'

const ROLES: { id: SearchAgent; name: string; doing: string }[] = [
  { id: 'interpreter', name: '解釈', doing: '問いかけを地域・期間・テーマに分けています' },
  { id: 'filter', name: '絞り込み', doing: '収集済みのイベントを条件で絞っています' },
  { id: 'scorer', name: '採点', doing: '関心との適合と関連度を採点しています' },
  { id: 'presenter', name: '提示', doing: '結果を並べています' },
]

const roleName = (id: SearchAgent) => ROLES.find((role) => role.id === id)?.name

function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

type Props = { reply: string; activity: SearchActivity[]; pending: boolean }

/** 探索を始めてからの経過秒。完了したら止める（「4.2秒で完了」と出す） */
function useElapsed(pending: boolean): number | null {
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!pending) return
    const started = Date.now()
    setStartedAt(started)
    setNow(started)
    const timer = window.setInterval(() => setNow(Date.now()), 100)
    return () => {
      window.clearInterval(timer)
      setNow(Date.now())
    }
  }, [pending])
  return startedAt === null ? null : Math.max(0, now - startedAt) / 1000
}

/**
 * 文字を流して出す（ChatGPT / Gemini の返答と同じ見せ方）。
 * 届いたばかりの文だけ流し、画面を開き直したときに古い文を打ち直さない。
 */
function TypeText({ text, animate }: { text: string; animate: boolean }) {
  const [shown, setShown] = useState(animate ? 0 : text.length)
  useEffect(() => {
    if (!animate) {
      setShown(text.length)
      return
    }
    setShown(0)
    const step = Math.max(1, Math.round(text.length / 40))
    const timer = window.setInterval(() => {
      setShown((count) => {
        const next = Math.min(text.length, count + step)
        if (next >= text.length) window.clearInterval(timer)
        return next
      })
    }, 16)
    return () => window.clearInterval(timer)
  }, [text, animate])
  return (
    <>
      {text.slice(0, shown)}
      {shown < text.length && <span className="type-caret" aria-hidden="true" />}
    </>
  )
}

/** 届いてから数秒以内の行だけ流す */
const isFresh = (iso: string) => Date.now() - new Date(iso).getTime() < 8000

/** エージェントの顔。考え中は色が回って脈打ち、終わると止まってチェックになる */
function AgentOrb({ state }: { state: 'thinking' | 'done' | 'warn' }) {
  return (
    <span className={`agent-orb is-${state}`} aria-hidden="true">
      <span className="agent-orb-core">{state === 'thinking' ? 'AI' : state === 'warn' ? '!' : '✓'}</span>
    </span>
  )
}

export function SearchActivityPanel({ reply, activity, pending }: Props) {
  // 役割ごとのカードは出さず、動きの行だけを時系列で見せる。探索中は届いた行から順に出る
  const last = activity[activity.length - 1]
  const nextIndex = last
    ? Math.min(ROLES.findIndex((role) => role.id === last.agent) + 1, ROLES.length - 1)
    : 0
  const nextRole = ROLES[nextIndex]
  const elapsed = useElapsed(pending)
  const warned = activity.some((line) => line.level === 'warn')
  const [replyFresh] = useState(() => pending)

  return (
    <div className={`activity${pending ? ' is-pending' : ''}`} role="status" aria-live="polite">
      <div className="activity-head">
        <AgentOrb state={pending ? 'thinking' : warned ? 'warn' : 'done'} />
        <p className={`activity-title${pending ? ' shimmer' : ''}`}>
          {pending ? (
            `${nextRole.name}: ${nextRole.doing}`
          ) : (
            <TypeText text={reply} animate={replyFresh} />
          )}
        </p>
        {elapsed !== null && (
          <span className="activity-elapsed">
            {pending ? `${elapsed.toFixed(1)}秒` : `${elapsed.toFixed(1)}秒で完了`}
          </span>
        )}
      </div>

      {/* 4 段の進み具合。いまの段が光り、終わった段はチェックになる */}
      <ol className="agent-steps" aria-label="エージェントの段階">
        {ROLES.map((role, index) => {
          const state = !pending
            ? activity.length > 0
              ? 'done'
              : 'waiting'
            : index < nextIndex
              ? 'done'
              : index === nextIndex
                ? 'active'
                : 'waiting'
          return (
            <li key={role.id} className={`agent-step is-${state}`}>
              <span className="agent-step-dot" aria-hidden="true">
                {state === 'done' ? '✓' : index + 1}
              </span>
              <span className="agent-step-name">{role.name}</span>
            </li>
          )
        })}
      </ol>

      {(activity.length > 0 || pending) && (
        <div className="activity-log">
          <ol>
            {activity.map((line, i) => (
              <li key={`${line.at}-${i}`} className={line.level === 'warn' ? 'is-warn' : 'is-done'}>
                <span className="log-icon" aria-hidden="true">
                  {line.level === 'warn' ? '!' : '✓'}
                </span>
                <span className="log-time">{timeOf(line.at)}</span>
                <span className="log-agent">{roleName(line.agent)}</span>
                <span className="log-message">
                  <TypeText text={line.message} animate={isFresh(line.at)} />
                </span>
              </li>
            ))}
            {/* いま動いている役割。最後の行の次の役割をグルグルと一緒に出す */}
            {pending && nextRole && (
              <li className="is-running" aria-hidden="true">
                <span className="log-icon">
                  <span className="spinner spinner-sm" />
                </span>
                <span className="log-time" />
                <span className="log-agent">{nextRole.name}</span>
                <span className="log-message shimmer">{nextRole.doing}</span>
              </li>
            )}
          </ol>
        </div>
      )}
    </div>
  )
}
