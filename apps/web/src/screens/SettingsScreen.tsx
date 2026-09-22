/** S-05 設定 */
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { loadProfile, summarizeProfile } from '../lib/profile'

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
