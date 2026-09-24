/**
 * プール探索エージェントの動き（ADR-010）。
 * 解釈 → 絞り込み → 採点 → 提示 の4役割。Web には出ないので数秒で終わり、
 * 完了した状態を「何をしたか」として、動きの行を時系列で見せる。
 */
import type { SearchActivity, SearchAgent } from '../types/api'

const ROLES: { id: SearchAgent; name: string }[] = [
  { id: 'interpreter', name: '解釈' },
  { id: 'filter', name: '絞り込み' },
  { id: 'scorer', name: '採点' },
  { id: 'presenter', name: '提示' },
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
  // 役割ごとのカードは出さず、動きの行だけを時系列で見せる
  return (
    <div className="activity tone-done" role="status" aria-live="polite">
      <div className="activity-head">
        <p className="activity-title">{pending ? '収集済みのイベントから探しています…' : reply}</p>
      </div>
      {activity.length > 0 && (
        <div className="activity-log">
          <ol>
            {activity.map((line, i) => (
              <li key={`${line.at}-${i}`} className={line.level === 'warn' ? 'is-warn' : ''}>
                <span className="log-time">{timeOf(line.at)}</span>
                <span className="log-agent">{ROLES.find((r) => r.id === line.agent)?.name}</span>
                <span className="log-message">{line.message}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}
