import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  emptyProfile,
  genres,
  isProfile,
  prefectures,
  travelTimeOptions,
} from '../lib/profile'
import type { Profile } from '../lib/profile'

type Props = {
  profile: Profile | null
  persisted: boolean
  onClose: () => void
  onSave: (profile: Profile, remember: boolean) => string | null
}

type ProfileTab = 'area' | 'interests'

export function ProfileDialog({ profile, persisted, onClose, onSave }: Props) {
  const [draft, setDraft] = useState<Profile>(profile ?? emptyProfile)
  const [activeTab, setActiveTab] = useState<ProfileTab>('area')
  const [prefectureMenuOpen, setPrefectureMenuOpen] = useState(false)
  const [remember] = useState(persisted || profile === null)
  const [error, setError] = useState('')

  function update<K extends keyof Profile>(key: K, value: Profile[K]) {
    setDraft((current) => ({ ...current, [key]: value }))
    setError('')
  }

  function toggleGenre(value: string) {
    setDraft((current) => ({
      ...current,
      genres: current.genres.includes(value)
        ? current.genres.filter((item) => item !== value)
        : [...current.genres, value],
    }))
    setError('')
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const value = {
      ...draft,
      originStation: draft.originStation.trim(),
      interestsPrompt: draft.interestsPrompt.trim(),
    }

    if (!value.originStation || value.locations.length === 0) {
      setActiveTab('area')
      setError('出発駅と対象エリアを設定してください。')
      return
    }
    if (value.genres.length === 0) {
      setActiveTab('interests')
      setError('興味のあるジャンルを1つ以上選択してください。')
      return
    }
    if (!isProfile(value)) {
      setError('入力内容を確認してください。')
      return
    }

    const saveError = onSave(value, remember)
    if (saveError) setError(saveError)
  }

  return (
    <section className="profile-editor panel" aria-labelledby="profile-title">
      <div className="profile-editor-header">
        <h2 id="profile-title">プロフィール編集</h2>
        <button type="button" className="icon-button" aria-label="プロフィール編集を閉じる" onClick={onClose}>
          ×
        </button>
      </div>
      <p className="profile-help">
        イベント検索に使う条件だけを設定します。設定はあとから変更できます。
      </p>

      <div className="profile-tabs" role="tablist" aria-label="プロフィール項目">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'area'}
          aria-controls="profile-area-panel"
          className={activeTab === 'area' ? 'is-active' : ''}
          onClick={() => {
            setActiveTab('area')
            setPrefectureMenuOpen(false)
          }}
        >
          エリア・移動条件
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'interests'}
          aria-controls="profile-interests-panel"
          className={activeTab === 'interests' ? 'is-active' : ''}
          onClick={() => {
            setActiveTab('interests')
            setPrefectureMenuOpen(false)
          }}
        >
          興味・関心
        </button>
      </div>

      <form onSubmit={submit}>
        {activeTab === 'area' ? (
          <div id="profile-area-panel" role="tabpanel" className="profile-fields">
            <label>
              出発駅（必須）
              <input
                required
                maxLength={80}
                value={draft.originStation}
                onChange={(event) => update('originStation', event.target.value)}
                placeholder="例：大阪駅"
              />
            </label>

            <div
              className="profile-prefecture-field"
              onKeyDown={(event) => {
                if (event.key === 'Escape') setPrefectureMenuOpen(false)
              }}
            >
              <span id="profile-prefecture-label">対象エリア（必須）</span>
              <button
                type="button"
                className="profile-select-trigger"
                aria-labelledby="profile-prefecture-label profile-prefecture-value"
                aria-expanded={prefectureMenuOpen}
                aria-controls="profile-prefecture-list"
                onClick={() => setPrefectureMenuOpen((open) => !open)}
              >
                <span id="profile-prefecture-value">{draft.locations[0] || '都道府県を選択'}</span>
                <span className="profile-select-chevron" aria-hidden="true" />
              </button>
              {prefectureMenuOpen && (
                <div
                  id="profile-prefecture-list"
                  className="profile-select-list"
                  role="listbox"
                  aria-labelledby="profile-prefecture-label"
                >
                  {prefectures.map((value) => {
                    const selected = draft.locations[0] === value
                    return (
                      <button
                        type="button"
                        role="option"
                        aria-selected={selected}
                        className={selected ? 'is-selected' : ''}
                        key={value}
                        onClick={() => {
                          update('locations', [value])
                          setPrefectureMenuOpen(false)
                        }}
                      >
                        {value}
                        {selected && <span aria-hidden="true">✓</span>}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            <fieldset>
              <legend>移動時間の目安</legend>
              <div className="profile-choices profile-time-choices">
                {travelTimeOptions.map((minutes) => (
                  <label className="profile-choice" key={minutes}>
                    <input
                      type="radio"
                      name="max-travel-minutes"
                      checked={draft.maxTravelMinutes === minutes}
                      onChange={() => update('maxTravelMinutes', minutes)}
                    />
                    {minutes}分以内
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="profile-check">
              <input
                type="checkbox"
                checked={draft.online}
                onChange={(event) => update('online', event.target.checked)}
              />
              オンラインイベントも候補に含める
            </label>
            <p className="profile-help">
              出発駅は、イベント詳細で駅すぱあとの経路・所要時間を表示する際にも使います。
            </p>
          </div>
        ) : (
          <div id="profile-interests-panel" role="tabpanel" className="profile-fields">
            <fieldset>
              <legend>興味のあるジャンル（1つ以上）</legend>
              <div className="profile-choices">
                {genres.map((value) => (
                  <label className="profile-choice" key={value}>
                    <input
                      type="checkbox"
                      checked={draft.genres.includes(value)}
                      onChange={() => toggleGenre(value)}
                    />
                    {value}
                  </label>
                ))}
              </div>
            </fieldset>
            <label>
              興味のあるテーマ（任意）
              <textarea
                rows={3}
                maxLength={300}
                value={draft.interestsPrompt}
                onChange={(event) => update('interestsPrompt', event.target.value)}
                placeholder="例：生成AI、GCP、地域課題、初心者歓迎"
              />
            </label>
          </div>
        )}

        <p className="profile-error" role="alert">{error}</p>
        <button type="submit" className="primary-button wide">検索条件を保存</button>
      </form>
    </section>
  )
}
