/**
 * Run の進捗バナー（画面設計書 §3.5）。
 * 全タブ共通で出す。チャットを閉じても進捗を追えるようにするため。
 */
import { useAppState } from '../state/AppState'
import { isRunning, runSummary, runTone, stepHint, stepLabel, stepProgress } from '../lib/runSteps'

export function RunProgressBanner() {
  const { run, runPending } = useAppState()

  if (runPending) {
    return (
      <div className="run-banner tone-caution" role="status">
        <p className="run-step">まだ実行中です</p>
        <p className="run-hint">
          しばらくしてから「イベントを更新」で最新の状態を確認してください。
        </p>
      </div>
    )
  }

  if (!run) return null

  const running = isRunning(run.status)
  const tone = runTone(run.status)
  const { index, total } = stepProgress(run.currentStep)
  const message = running
    ? stepLabel(run.currentStep)
    : runSummary(run.status, run)
  const hint = running ? stepHint(run.currentStep) : run.errorMessage ?? undefined

  return (
    <div className={`run-banner tone-${tone}`} role="status">
      <div className="run-top">
        <p className="run-step">{message}</p>
        {running && (
          <span className="run-count">
            {index} / {total}
          </span>
        )}
      </div>
      <div className="run-bar">
        <i style={{ width: `${Math.round((index / total) * 100)}%` }} />
      </div>
      {hint && <p className="run-hint">{hint}</p>}
      {running && <p className="run-hint">閉じても探索は続きます。</p>}
    </div>
  )
}
