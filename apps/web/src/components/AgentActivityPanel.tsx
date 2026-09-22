/**
 * エージェントの動き（画面設計書 §3.5 の進捗表示を拡張）。
 *
 * バックエンドは §6 の決定論的なパイプラインで、ここでは4つの役割に分けて見せる:
 * 計画（normalize / plan）→ 検索（search / fetch）→ 抽出・検証（extract_validate）
 * → 整理（dedupe / rank / save）。各役割の状態と直近の行動を並べ、全行は
 * 折りたたみで読める。全画面共通で本文の最上部に出す。
 */
import { useState } from 'react'
import { useAppState } from '../state/AppState'
import { isRunning, runSummary, runTone, stepLabel, stepProgress } from '../lib/runSteps'
import type { AgentRun, RunActivity, RunAgent } from '../types/api'

type Role = { id: RunAgent; name: string; hint: string; steps: string[] }

const ROLES: Role[] = [
  { id: 'planner', name: '計画', hint: '関心条件から検索クエリを組み立てる', steps: ['queued', 'normalize', 'plan'] },
  { id: 'searcher', name: '検索', hint: 'Web を検索し、公開ページを取得する', steps: ['search'] },
  { id: 'extractor', name: '抽出・検証', hint: '申込締切と開催日を分けて確認する', steps: ['extract_validate'] },
  { id: 'organizer', name: '整理', hint: '重複を束ね、おすすめ順に並べて保存する', steps: ['dedupe', 'rank', 'save', 'completed'] },
]

type RoleState = 'waiting' | 'running' | 'done' | 'failed'

function roleStates(run: AgentRun): Record<RunAgent, RoleState> {
  const running = isRunning(run.status)
  const failed = run.status === 'failed'
  const current = ROLES.findIndex((role) => role.steps.includes(run.currentStep ?? 'queued'))
  const states = {} as Record<RunAgent, RoleState>
  ROLES.forEach((role, index) => {
    if (!running && !failed) states[role.id] = 'done'
    else if (failed) states[role.id] = index < current ? 'done' : index === current ? 'failed' : 'waiting'
    else states[role.id] = index < current ? 'done' : index === current ? 'running' : 'waiting'
  })
  return states
}

const STATE_LABEL: Record<RoleState, string> = {
  waiting: '待機',
  running: '実行中',
  done: '完了',
  failed: '中断',
}

function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function AgentActivityPanel() {
  const { run, runPending } = useAppState()
  const [open, setOpen] = useState(false)

  if (runPending) {
    return (
      <div className="activity tone-caution" role="status">
        <p className="activity-title">まだ実行中です</p>
        <p className="fine">しばらくしてから再読み込みすると最新の一覧になります。</p>
      </div>
    )
  }
  if (!run) return null

  const running = isRunning(run.status)
  const tone = runTone(run.status)
  const { index, total } = stepProgress(run.currentStep)
  const title = running ? stepLabel(run.currentStep) : runSummary(run.status, run)
  const states = roleStates(run)
  const activity = run.activity ?? []
  const byRole = (id: RunAgent): RunActivity[] => activity.filter((line) => line.agent === id)

  return (
    <div className={`activity tone-${tone}`} role="status" aria-live="polite">
      <div className="activity-head">
        <p className="activity-title">{title}</p>
        {running && (
          <span className="run-count">
            {index} / {total}
          </span>
        )}
      </div>
      {running && (
        <div className="run-bar">
          <i style={{ width: `${Math.round((index / total) * 100)}%` }} />
        </div>
      )}
      {run.errorMessage && !running && <p className="fine warn">{run.errorMessage}</p>}

      <div className="agents">
        {ROLES.map((role) => {
          const lines = byRole(role.id)
          const last = lines[lines.length - 1]
          const state = states[role.id]
          return (
            <div key={role.id} className={`agent is-${state}`}>
              <div className="agent-head">
                <span className="agent-dot" aria-hidden="true" />
                <span className="agent-name">{role.name}</span>
                <span className="agent-state">{STATE_LABEL[state]}</span>
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
