/**
 * Agent Run の進捗表示（画面設計書 §3.5）。
 *
 * 識別子は services/agent/src/event_agent/workflows/collect.py の実装値。
 * 生の識別子をそのままユーザーに見せない。バックエンドがステップを増やしても
 * 画面が壊れないよう、未知の値にはフォールバックを返す。
 */
import type { AgentRunStatus } from '../types/api'

export type RunStep = {
  id: string
  label: string
  hint?: string
}

export const RUN_STEPS: RunStep[] = [
  { id: 'normalize', label: '関心条件を整理しています', hint: '地域・対象年・オンライン可否を確定' },
  { id: 'plan', label: '検索計画を作成しています', hint: '検索クエリを組み立て' },
  { id: 'search', label: 'Webを検索しています', hint: '公開情報を収集' },
  {
    id: 'extract_validate',
    label: '日程を抽出・検証しています',
    hint: '申込締切と開催日を分けて確認',
  },
  { id: 'dedupe', label: '重複を整理しています' },
  { id: 'rank', label: 'おすすめ順に並べています' },
  { id: 'save', label: '保存しています' },
  { id: 'completed', label: '完了しました' },
]

const BY_ID = new Map(RUN_STEPS.map((step) => [step.id, step]))

export function stepLabel(currentStep?: string | null): string {
  if (!currentStep) return '準備しています'
  if (currentStep === 'queued') return '受け付けました'
  if (currentStep === 'failed') return '取得に失敗しました'
  return BY_ID.get(currentStep)?.label ?? '処理中…'
}

export function stepHint(currentStep?: string | null): string | undefined {
  if (!currentStep) return undefined
  return BY_ID.get(currentStep)?.hint
}

/** 進捗は経過時間ではなくステップ番号で示す。偽の残り時間を出さない。 */
export function stepProgress(currentStep?: string | null): { index: number; total: number } {
  const total = RUN_STEPS.length
  if (!currentStep || currentStep === 'queued') return { index: 0, total }
  const found = RUN_STEPS.findIndex((step) => step.id === currentStep)
  return { index: found < 0 ? 0 : found + 1, total }
}

export function isRunning(status?: AgentRunStatus): boolean {
  return status === 'queued' || status === 'running'
}

/** 完了時の要約。partial_success は失敗扱いにしない（§3.5）。 */
export function runSummary(
  status: AgentRunStatus,
  counts: { verifiedCount?: number; partialCount?: number; quarantinedCount?: number },
): string {
  const shown = (counts.verifiedCount ?? 0) + (counts.partialCount ?? 0)
  if (status === 'succeeded') return `${shown}件のイベントを更新しました`
  if (status === 'partial_success') {
    const held = counts.quarantinedCount ?? 0
    return held > 0
      ? `${shown}件を更新しました（${held}件は情報が足りず保留）`
      : `${shown}件を更新しました`
  }
  if (status === 'cancelled') return '中止しました'
  return '取得に失敗しました'
}

export type RunTone = 'running' | 'done' | 'caution' | 'error'

export function runTone(status?: AgentRunStatus): RunTone {
  if (status === 'succeeded') return 'done'
  if (status === 'partial_success') return 'caution'
  if (status === 'failed') return 'error'
  return 'running'
}
