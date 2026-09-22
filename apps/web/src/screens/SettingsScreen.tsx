/** S-05 設定 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { ProfileDialog } from '../components/ProfileDialog'
import { loadProfile, profileStorageKey } from '../lib/profile'
import { RunProgressBanner } from '../components/RunProgressBanner'
import type { Profile } from '../lib/profile'

export function SettingsScreen() {
  const { run, calendar } = useAppState()
  const navigate = useNavigate()
  const [profileOpen, setProfileOpen] = useState(false)
  const [initial] = useState(loadProfile)
  const [profile, setProfile] = useState<Profile | null>(initial.profile)
  const [persisted, setPersisted] = useState(initial.profile !== null)
  const [profileNotice, setProfileNotice] = useState(initial.notice)

  const saveProfile = (value: Profile, remember: boolean): string | null => {
    try {
      if (remember) localStorage.setItem(profileStorageKey, JSON.stringify(value))
      else localStorage.removeItem(profileStorageKey)
    } catch {
      // 既存の保存内容が残る場合は、保存解除に成功したと表示しない。
      if (remember || persisted) {
        return 'ブラウザの保存設定を変更できませんでした。設定を確認して再度お試しください。'
      }
    }
    setProfile(value)
    setPersisted(remember)
    setProfileNotice('')
    setProfileOpen(false)
    return null
  }

  const registeredCount = Object.keys(calendar).length

  return (
    <>
      <header className="app-header">
        <div className="header-main">
          <h1 className="header-compact">設定</h1>
        </div>
      </header>

      <RunProgressBanner />

      <div className="scroll-area">
        <div className="settings">
          {profileOpen ? (
            <ProfileDialog
              profile={profile}
              persisted={persisted}
              onClose={() => setProfileOpen(false)}
              onSave={saveProfile}
            />
          ) : (
            <>
          <section className="panel">
            <h3>アカウント</h3>
            <div className="setting-row">
              <span className="setting-key">
                Yuya Kaneko
                <small>yuya@example.com</small>
              </span>
              <span className="chip chip-mock">モック</span>
            </div>
            <button type="button" className="ghost-button wide">
              Googleでログイン（モック）
            </button>
          </section>

          <section className="panel">
            <h3>関心条件</h3>
            <p className="prompt-box">
              {profile
                ? [
                    `${profile.originStation}から${profile.maxTravelMinutes}分以内`,
                    ...profile.locations,
                    ...profile.genres,
                    profile.interestsPrompt,
                  ]
                    .filter(Boolean)
                    .join('・')
                : 'ハッカソン、生成AI、GCP、関西エリア。オンライン参加も可。'}
            </p>
            {profileNotice && <p className="fine warn-text">{profileNotice}</p>}
            <div className="setting-row">
              <span className="setting-key">対象年</span>
              <span className="muted">2026年</span>
            </div>
            <div className="setting-row">
              <span className="setting-key">オンラインも含める</span>
              <button
                type="button"
                role="switch"
                aria-checked={profile?.online ?? true}
                aria-label="オンラインも含める"
                className="switch"
                onClick={() => setProfileOpen(true)}
              />
            </div>
            <button type="button" className="ghost-button wide" onClick={() => setProfileOpen(true)}>
              プロフィールを編集
            </button>
            <button type="button" className="ghost-button wide" onClick={() => navigate('/agent')}>
              エージェントに相談して調整する
            </button>
          </section>

          <section className="panel">
            <h3>連携</h3>
            <div className="setting-row">
              <span className="setting-key">
                Googleカレンダー
                <small>モック接続（デモ）。実際には書き込みません</small>
              </span>
              <span className="chip chip-mock">モック</span>
            </div>
            <div className="setting-row">
              <span className="setting-key">
                登録済みのイベント
                <small>この端末に保存されています</small>
              </span>
              <span className="muted">{registeredCount}件</span>
            </div>
          </section>

          <section className="panel">
            <h3>通知</h3>
            <div className="setting-row">
              <span className="setting-key">
                毎朝7時の自動更新
                <small>Phase 2 で対応予定</small>
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={false}
                aria-label="毎朝7時の自動更新"
                className="switch"
                disabled
              />
            </div>
          </section>

          <details className="panel">
            <summary>最新の探索結果（デバッグ）</summary>
            {run ? (
              <dl className="definitions">
                <dt>runId</dt>
                <dd className="mono">{run.runId}</dd>
                <dt>status</dt>
                <dd>{run.status}</dd>
                <dt>検索クエリ</dt>
                <dd>{run.queryCount ?? 0} 件</dd>
                <dt>候補</dt>
                <dd>{run.candidateCount ?? 0} 件</dd>
                <dt>確認済み</dt>
                <dd>{run.verifiedCount ?? 0} 件</dd>
                <dt>要確認</dt>
                <dd>{run.partialCount ?? 0} 件</dd>
                <dt>保留</dt>
                <dd>{run.quarantinedCount ?? 0} 件</dd>
              </dl>
            ) : (
              <p className="event-meta">まだ探索を実行していません。</p>
            )}
            <p className="fine">保留（quarantined）は件数のみ表示し、内容は表示しません。</p>
          </details>

          <p className="fine">
            イベント情報は公開Web情報をもとにAIが整理したものです。申込前に必ず公式サイトをご確認ください。
          </p>
            </>
          )}
        </div>
      </div>
    </>
  )
}
