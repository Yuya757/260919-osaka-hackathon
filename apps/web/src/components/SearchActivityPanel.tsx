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

export function SearchActivityPanel({ reply, activity, pending }: Props) {
  // 役割ごとのカードは出さず、動きの行だけを時系列で見せる。探索中は届いた行から順に出る
  const last = activity[activity.length - 1]
  const nextRole = last
    ? ROLES[Math.min(ROLES.findIndex((role) => role.id === last.agent) + 1, ROLES.length - 1)]
    : ROLES[0]
  const elapsed = useElapsed(pending)
  const warned = activity.some((line) => line.level === 'warn')

  return (
    <div className={`activity${pending ? ' is-pending' : ''}`} role="status" aria-live="polite">
      <div className="activity-head">
        {/* 探索中はグルグル、終わったらチェック（警告があれば !） */}
        <span
          className={`activity-icon ${pending ? 'spinner' : warned ? 'is-warn' : 'is-done'}`}
          aria-hidden="true"
        >
          {pending ? null : warned ? '!' : '✓'}
        </span>
        <p className={`activity-title${pending ? ' shimmer' : ''}`}>
          {pending ? `${nextRole.name}: ${nextRole.doing}` : reply}
        </p>
        {elapsed !== null && (
          <span className="activity-elapsed">
            {pending ? `${elapsed.toFixed(1)}秒` : `${elapsed.toFixed(1)}秒で完了`}
          </span>
        )}
      </div>
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
                <span className="log-message">{line.message}</span>
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
