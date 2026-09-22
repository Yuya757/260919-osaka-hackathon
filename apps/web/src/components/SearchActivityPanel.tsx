/**
 * プール探索エージェントの動き（ADR-010）。
 * 解釈 → 絞り込み → 採点 → 提示 の4役割。Web には出ないので数秒で終わり、
 * 完了した状態を「何をしたか」として見せる。
 */
import { useState } from 'react'
import type { SearchActivity, SearchAgent } from '../types/api'

const ROLES: { id: SearchAgent; name: string; hint: string }[] = [
  { id: 'interpreter', name: '解釈', hint: '問いかけを地域・期間・テーマに分ける' },
  { id: 'filter', name: '絞り込み', hint: '収集済みのプールを条件で絞る' },
  { id: 'scorer', name: '採点', hint: '関心との適合と関連度で並べる' },
  { id: 'presenter', name: '提示', hint: '結果を一覧に出す' },
]

function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

type Props = { reply: string; activity: SearchActivity[]; pending: boolean }

export function SearchActivityPanel({ reply, activity, pending }: Props) {
  const [open, setOpen] = useState(false)
  const byRole = (id: SearchAgent) => activity.filter((line) => line.agent === id)
  const reached = new Set(activity.map((line) => line.agent))

  return (
    <div className="activity tone-done" role="status" aria-live="polite">
      <div className="activity-head">
        <p className="activity-title">{pending ? '収集済みのイベントから探しています…' : reply}</p>
      </div>
      <div className="agents">
        {ROLES.map((role) => {
          const lines = byRole(role.id)
          const last = lines[lines.length - 1]
          const state = pending ? (reached.has(role.id) ? 'done' : 'running') : reached.has(role.id) ? 'done' : 'waiting'
          return (
            <div key={role.id} className={`agent is-${state}`}>
              <div className="agent-head">
                <span className="agent-dot" aria-hidden="true" />
                <span className="agent-name">{role.name}</span>
                <span className="agent-state">
                  {state === 'done' ? '完了' : state === 'running' ? '実行中' : '待機'}
                </span>
              </div>
              <p className={`agent-last${last?.level === 'warn' ? ' is-warn' : ''}`}>
                {last ? last.message : role.hint}
              </p>
            </div>
          )
        })}
      </div>
      {activity.length > 0 && (
        <div className="activity-log">
          <button type="button" className="link-button" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            {open ? '動きを閉じる' : `すべての動きを見る（${activity.length}）`}
          </button>
          {open && (
            <ol>
              {activity.map((line, i) => (
                <li key={`${line.at}-${i}`} className={line.level === 'warn' ? 'is-warn' : ''}>
                  <span className="log-time">{timeOf(line.at)}</span>
                  <span className="log-agent">{ROLES.find((r) => r.id === line.agent)?.name}</span>
                  <span className="log-message">{line.message}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  )
}
