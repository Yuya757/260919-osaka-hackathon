/**
 * プール探索エージェントの動き（ADR-010）。
 * 解釈 → 絞り込み → 採点 → 提示 の4役割。Web には出ないので数秒で終わり、
 * 完了した状態を「何をしたか」として、動きの行を時系列で見せる。
 */
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

export function SearchActivityPanel({ reply, activity, pending }: Props) {
  // 役割ごとのカードは出さず、動きの行だけを時系列で見せる。探索中は届いた行から順に出る
  const last = activity[activity.length - 1]
  const nextRole = last
    ? ROLES[Math.min(ROLES.findIndex((role) => role.id === last.agent) + 1, ROLES.length - 1)]
    : ROLES[0]

  return (
    <div className="activity tone-done" role="status" aria-live="polite">
      <div className="activity-head">
        <p className="activity-title">{pending ? '収集済みのイベントから探しています…' : reply}</p>
      </div>
      {(activity.length > 0 || pending) && (
        <div className="activity-log">
          <ol>
            {activity.map((line, i) => (
              <li key={`${line.at}-${i}`} className={line.level === 'warn' ? 'is-warn' : ''}>
                <span className="log-time">{timeOf(line.at)}</span>
                <span className="log-agent">{roleName(line.agent)}</span>
                <span className="log-message">{line.message}</span>
              </li>
            ))}
            {/* いま動いている役割。最後の行の次の役割を「…中」で出す */}
            {pending && nextRole && (
              <li className="is-running" aria-hidden="true">
                <span className="log-time" />
                <span className="log-agent">{nextRole.name}</span>
                <span className="log-message">
                  {nextRole.doing}
                  <span className="log-dots" />
                </span>
              </li>
            )}
          </ol>
        </div>
      )}
    </div>
  )
}
