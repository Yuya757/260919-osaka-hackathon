/**
 * カレンダー登録シート（画面設計書 S-07 / 上位§5-2 / §10.4）。
 *
 * 上位§5-2 が求める3アクションは、360px幅にボタン3つを並べるとラベルが読めない
 * ため、2つのトグルとラベルが変わる単一CTAで表現する。要求されている文言は
 * すべてCTAラベルとして実際に出る。
 *
 * §10.4 の human-in-the-loop: シートを開くだけでは副作用ゼロ。CTAを押した
 * ときだけ登録する。登録される内容は押す前にすべて提示する。
 */
import { useEffect, useState } from 'react'
import type { Event } from '../types/api'
import { canRegisterDeadline, deadlineLabel, heldLabel } from '../lib/eventView'
import { BottomSheet } from './BottomSheet'
import { CheckIcon } from './Icon'

type Props = {
  event: Event | null
  onClose: () => void
  onConfirm: (event: Event, selection: { deadline: boolean; main: boolean }) => Promise<void>
}

export function CalendarSheet({ event, onClose, onConfirm }: Props) {
  const deadlineAvailable = event ? canRegisterDeadline(event) : false
  const [deadline, setDeadline] = useState(deadlineAvailable)
  const [main, setMain] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    setDeadline(deadlineAvailable)
    setMain(true)
    setError(null)
    setDone(false)
  }, [event, deadlineAvailable])

  if (!event) return null

  // 上位§5-2 の3つの文言をそのままCTAに出す
  const ctaLabel =
    deadline && main
      ? '両方まとめて登録'
      : deadline
        ? '申込締切を登録'
        : main
          ? '本番日程を登録'
          : '登録する項目を選択してください'

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await onConfirm(event, { deadline, main })
      setDone(true)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '登録に失敗しました。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <BottomSheet open onClose={onClose} label="カレンダーに登録">
      <h2 className="sheet-title">カレンダーに登録</h2>
      <p className="sheet-sub">{event.title}</p>

      {done ? (
        <>
          <p className="sheet-done">
            <CheckIcon /> カレンダーに登録しました（デモ）
          </p>
          <p className="sheet-note">
            実際のGoogleカレンダーには書き込んでいません。設定画面から連携状態を確認できます。
          </p>
          <button type="button" className="primary-button wide" onClick={onClose}>
            閉じる
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            role="checkbox"
            aria-checked={deadlineAvailable && deadline}
            aria-disabled={!deadlineAvailable}
            aria-describedby={deadlineAvailable ? undefined : 'deadline-reason'}
            className={`option${deadlineAvailable && deadline ? ' is-on' : ''}${
              deadlineAvailable ? '' : ' is-disabled'
            }`}
            onClick={() => deadlineAvailable && setDeadline((v) => !v)}
          >
            <span className="option-box" aria-hidden="true">
              {deadlineAvailable && deadline ? <CheckIcon /> : null}
            </span>
            <span className="option-text">
              <b>申込締切をリマインダーとして登録</b>
              <small id={deadlineAvailable ? undefined : 'deadline-reason'}>
                {deadlineAvailable
                  ? `${deadlineLabel(event)} · 1日前と3時間前に通知`
                  : '申込締切が未確認のため登録できません'}
              </small>
            </span>
          </button>

          <button
            type="button"
            role="checkbox"
            aria-checked={main}
            className={`option${main ? ' is-on' : ''}`}
            onClick={() => setMain((v) => !v)}
          >
            <span className="option-box" aria-hidden="true">
              {main ? <CheckIcon /> : null}
            </span>
            <span className="option-text">
              <b>本番日程を登録</b>
              <small>{heldLabel(event)}</small>
            </span>
          </button>

          <div className="sheet-row">
            <span>登録先</span>
            <span className="muted">yuya@example.com（モック）</span>
          </div>

          <p className="sheet-warn">
            ⚠ デモ版です。実際のGoogleカレンダーには書き込みません。
          </p>

          {error && <p className="sheet-error">{error}</p>}

          <button
            type="button"
            className="primary-button wide"
            disabled={busy || (!deadline && !main)}
            onClick={() => void submit()}
          >
            {busy ? '登録しています…' : ctaLabel}
          </button>
          <button type="button" className="ghost-button wide" onClick={onClose}>
            キャンセル
          </button>
        </>
      )}
    </BottomSheet>
  )
}
