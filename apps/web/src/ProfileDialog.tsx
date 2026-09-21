import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { emptyProfile, genres, isProfile, prefectures } from './profile'
import type { Profile } from './profile'

type Props = {
  profile: Profile | null
  persisted: boolean
  onClose: () => void
  onSave: (profile: Profile, remember: boolean) => string | null
}

export function ProfileDialog({ profile, persisted, onClose, onSave }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const [draft, setDraft] = useState<Profile>(profile ?? emptyProfile)
  const [step, setStep] = useState(0)
  const [remember, setRemember] = useState(persisted)
  const [error, setError] = useState('')

  useEffect(() => {
    const element = dialog.current
    const previousFocus = document.activeElement
    element?.showModal()
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      element?.close()
      document.body.style.overflow = previousOverflow
      if (previousFocus instanceof HTMLElement) previousFocus.focus()
    }
  }, [])

  useEffect(() => {
    heading.current?.focus()
    dialog.current?.scrollTo(0, 0)
  }, [step])

  function update<K extends keyof Profile>(key: K, value: Profile[K]) {
    setDraft(current => ({ ...current, [key]: value }))
    setError('')
  }

  function toggleGenre(value: string) {
    setDraft(current => ({
      ...current,
      genres: current.genres.includes(value)
        ? current.genres.filter(item => item !== value)
        : [...current.genres, value],
    }))
    setError('')
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (step === 0) { setStep(1); return }
    if (draft.genres.length === 0) {
      setError('ジャンルを1つ以上選択してください。')
      event.currentTarget.querySelector<HTMLInputElement>('[name="genre"]')?.focus()
      return
    }
    const value = { ...draft, city: draft.city.trim(), keywords: draft.keywords.trim(), excluded: draft.excluded.trim(), snsInterests: draft.snsInterests.trim() }
    if (!isProfile(value)) { setError('入力内容を確認してください。「戻る」から修正できます。'); return }
    const saveError = onSave(value, remember)
    if (saveError) setError(saveError)
  }

  return (
    <dialog ref={dialog} className="profile-dialog" aria-labelledby="profile-title" onCancel={onClose}>
      <div className="profile-dialog-header">
        <span>{profile ? 'プロフィール編集' : 'プロフィール新規登録'} · STEP {step + 1} / 2</span>
        <button type="button" aria-label="プロフィールを閉じる" onClick={onClose}>×</button>
      </div>
      <ol className="profile-steps">
        <li aria-current={step === 0 ? 'step' : undefined}>1 エリア・移動条件</li>
        <li aria-current={step === 1 ? 'step' : undefined}>2 興味・関心</li>
      </ol>
      <h2 id="profile-title" tabIndex={-1} ref={heading}>{step === 0 ? '参加しやすい場所を教えてください' : '興味のあるジャンルを選びましょう'}</h2>
      <p className="profile-help">設定はあとから変更できます。</p>
      <form onSubmit={submit}>
        {step === 0 ? <div className="profile-fields">
          <label>居住エリア（必須）<select required value={draft.prefecture} onChange={event => update('prefecture', event.target.value)} autoComplete="address-level1">
            <option value="">都道府県を選択</option>
            {prefectures.map(value => <option key={value}>{value}</option>)}
          </select></label>
          <label>市区町村（任意）<input value={draft.city} onChange={event => update('city', event.target.value)} maxLength={60} placeholder="例：大阪市" autoComplete="address-level2" /></label>
          <p className="profile-help">番地や建物名の入力は不要です。</p>
          <label>移動できる距離の目安（km以内・必須）<input type="number" required min={1} max={1000} step={1} value={Number.isNaN(draft.distance) ? '' : draft.distance} onChange={event => update('distance', event.target.valueAsNumber)} /></label>
          <label>駅からの徒歩時間（分以内・必須）<input type="number" required min={1} max={120} step={1} value={Number.isNaN(draft.walkMinutes) ? '' : draft.walkMinutes} onChange={event => update('walkMinutes', event.target.valueAsNumber)} /></label>
          <p className="profile-help">最寄り駅から会場までの徒歩時間です。オンライン開催には適用しません。</p>
          <label className="profile-check"><input type="checkbox" checked={draft.online} onChange={event => update('online', event.target.checked)} />オンラインのイベントも候補に含める</label>
        </div> : <div className="profile-fields">
          <fieldset><legend>興味のあるジャンル（1つ以上）</legend><div className="profile-choices">
            {genres.map(value => <label className="profile-choice" key={value}><input type="checkbox" name="genre" checked={draft.genres.includes(value)} onChange={() => toggleGenre(value)} />{value}</label>)}
          </div></fieldset>
          <label>追加キーワード（任意）<textarea rows={2} maxLength={300} value={draft.keywords} onChange={event => update('keywords', event.target.value)} placeholder="例：生成AI、GCP、Rust、初心者歓迎" /></label>
          <label>興味のないジャンル（任意）<input maxLength={200} value={draft.excluded} onChange={event => update('excluded', event.target.value)} placeholder="例：投資セミナー、営業交流会" /></label>
          <details className="profile-sns"><summary>SNSの情報も検索に使う（任意）</summary>
            <p className="profile-help">SNS連携は準備中です。興味の情報を手入力できます。</p>
            {['X', 'Instagram'].map(value => <div className="profile-sns-row" key={value}><strong>{value}</strong><button type="button" disabled>未接続・準備中</button></div>)}
            <label>SNSに登録している興味（任意）<textarea rows={2} maxLength={300} value={draft.snsInterests} onChange={event => update('snsInterests', event.target.value)} placeholder="例：生成AI、クラウド、スタートアップ" /></label>
          </details>
          <label className="profile-check"><input type="checkbox" checked={remember} onChange={event => setRemember(event.target.checked)} />この端末のブラウザにプロフィールを保存する</label>
          <p className="profile-help">チェックしない場合、再読み込みで内容は消えます。サーバーには送信しません。登録した条件によるイベント検索は準備中です。</p>
        </div>}
        <p className="profile-error" role="alert">{error}</p>
        <div className="profile-actions">
          <button type="button" onClick={() => { if (step === 0) onClose(); else { setStep(0); setError('') } }}>{step === 0 ? 'あとで設定' : '← 戻る'}</button>
          <button type="submit" className="refresh-button">{step === 0 ? '次へ →' : profile ? '変更を保存' : '登録を完了'}</button>
        </div>
      </form>
    </dialog>
  )
}
