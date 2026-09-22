/**
 * プロフィール（興味・条件）をカード式ステップで選ぶ。
 * 1画面1問。最後のステップで保存し、ホームへ戻る。途中の「あとで設定」は保存しない。
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { emptyProfile, loadProfile, profileSteps, saveProfile } from '../lib/profile'
import type { Profile, ProfileGroup } from '../lib/profile'

export function ProfileScreen() {
  const navigate = useNavigate()
  const [draft, setDraft] = useState<Profile>(() => loadProfile().profile ?? emptyProfile)
  const [index, setIndex] = useState(0)
  const [error, setError] = useState('')
  const heading = useRef<HTMLHeadingElement>(null)

  const step = profileSteps[index]
  const picked = draft[step.key]
  const last = index === profileSteps.length - 1

  useEffect(() => {
    heading.current?.focus()
  }, [index])

  const toggle = (group: ProfileGroup, value: string, multi: boolean) => {
    setDraft((current) => {
      const cur = current[group]
      const next = multi
        ? cur.includes(value)
          ? cur.filter((v) => v !== value)
          : [...cur, value]
        : [value]
      return { ...current, [group]: next }
    })
    setError('')
  }

  const prev = () => {
    if (index === 0) navigate('/settings')
    else setIndex(index - 1)
  }

  const next = () => {
    if (!last) {
      setIndex(index + 1)
      return
    }
    if (!saveProfile(draft)) {
      setError('ブラウザに保存できませんでした。プライベートウィンドウでは保存されません。')
      return
    }
    navigate('/')
  }

  return (
    <div className="profile">
      <div className="profile-top">
        <button type="button" className="back" onClick={() => navigate('/settings')}>
          ← 設定へ
        </button>
        <span className="profile-count">
          {index + 1} / {profileSteps.length}
        </span>
      </div>

      <div className="step-bars" aria-hidden="true">
        {profileSteps.map((s, i) => (
          <span key={s.key} className={i <= index ? 'is-done' : ''} />
        ))}
      </div>

      <div className="step-card">
        <div className="step-head">
          <h1 tabIndex={-1} ref={heading}>
            {step.title}
          </h1>
          <p>{step.help}</p>
        </div>

        <div className="step-options" role="group" aria-label={step.title}>
          {step.options.map((label) => {
            const on = picked.includes(label)
            return (
              <button
                key={label}
                type="button"
                className={`pill${on ? ' is-on' : ''}`}
                aria-pressed={on}
                onClick={() => toggle(step.key, label, step.multi)}
              >
                {label}
              </button>
            )
          })}
        </div>

        {error && (
          <p className="fine warn" role="alert">
            {error}
          </p>
        )}

        <div className="step-foot">
          <button type="button" className="link-button" onClick={prev}>
            {index === 0 ? 'あとで設定' : '← 戻る'}
          </button>
          <span className="spacer" />
          <span className="step-selected">
            {picked.length ? `${picked.length}個選択中` : '未選択'}
          </span>
          <button type="button" className="button button-primary" onClick={next}>
            {last ? '保存して一覧へ' : '次へ'}
          </button>
        </div>
      </div>

      <p className="fine">
        選んだ内容はこの端末にだけ保存し、サーバーには送信しません。推薦の並び順への反映は準備中です。
      </p>
    </div>
  )
}
