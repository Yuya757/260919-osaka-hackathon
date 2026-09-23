/** S-05 設定 */
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { loadHomeStation, saveHomeStation } from '../lib/homeStation'
import { loadProfile, summarizeProfile } from '../lib/profile'

/** 最寄駅の登録。経路検索で出発駅として最初から入る */
function HomeStationCard() {
  const [saved, setSaved] = useState(loadHomeStation)
  const [draft, setDraft] = useState(saved)
  const [message, setMessage] = useState('')

  const onSave = (event: FormEvent) => {
    event.preventDefault()
    if (!saveHomeStation(draft)) {
      setMessage('ブラウザに保存できませんでした。プライベートウィンドウでは保存されません。')
      return
    }
    const next = loadHomeStation()
    setSaved(next)
    setDraft(next)
    setMessage(next ? `${next}駅を登録しました。` : '最寄駅の登録を消しました。')
  }

  return (
    <div className="profile-card">
      <p className="profile-summary">
        {saved ? `${saved}駅` : 'まだ登録されていません。'}
        <br />
        <span className="fine">イベント詳細の「会場までの経路」で出発駅として使います。</span>
      </p>
      <form className="route-form" onSubmit={onSave}>
        <label className="sr-only" htmlFor="home-station">
          最寄駅
        </label>
        <input
          id="home-station"
          value={draft}
          placeholder="駅名（例: 札幌、博多、梅田）"
          maxLength={40}
          autoComplete="off"
          onChange={(event) => {
            setDraft(event.target.value)
            setMessage('')
          }}
        />
        <button type="submit" disabled={draft.trim().replace(/駅$/, '') === saved}>
          {saved && !draft.trim() ? '登録を消す' : '保存'}
        </button>
      </form>
      {message && (
        <p className="fine" role="status">
          {message}
        </p>
      )}
    </div>
  )
}

export function SettingsScreen() {
  const { run, calendar } = useAppState()
  const navigate = useNavigate()
  const { profile, notice } = loadProfile()
  const registeredCount = Object.keys(calendar).length

  return (
    <div className="settings">
      <h1>設定</h1>

      <section className="settings-section">
        <p className="eyebrow">プロフィール</p>
        <div className="profile-card">
          <p className="profile-summary">
            {profile
              ? summarizeProfile(profile) || 'まだ何も選んでいません。'
              : 'まだ設定されていません。行ける範囲や興味のあるジャンルを選べます。'}
          </p>
          {notice && <p className="fine warn">{notice}</p>}
          <button type="button" className="button" onClick={() => navigate('/settings/profile')}>
            {profile ? '興味を編集する' : '興味を選ぶ'}
          </button>
        </div>
      </section>

      <section className="settings-section">
        <p className="eyebrow">最寄駅</p>
        <HomeStationCard />
      </section>

      <section className="settings-section">
        <p className="eyebrow">アカウントと連携</p>
        <div className="setting-row">
          <span className="setting-key">
            Yuya Kaneko
            <small>yuya@example.com</small>
          </span>
          <span className="setting-state">モック</span>
        </div>
        <div className="setting-row">
          <span className="setting-key">
            Googleカレンダー
            <small>登録済み {registeredCount}件（この端末に保存。実際には書き込みません）</small>
          </span>
          <span className="setting-state">モック</span>
        </div>
        <div className="setting-row">
          <span className="setting-key">
            毎朝7時の自動更新
            <small>Phase 2 で対応予定</small>
          </span>
          <span className="setting-state">準備中</span>
        </div>
      </section>

      <details className="settings-debug">
        <summary>最新の探索結果</summary>
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
          <p className="fine">まだ探索を実行していません。</p>
        )}
        <p className="fine">保留（quarantined）は件数のみ表示し、内容は表示しません。</p>
      </details>

      <p className="fine">
        イベント情報は公開Web情報をもとにAIが整理したものです。申込前に必ず公式サイトをご確認ください。
      </p>
    </div>
  )
}
