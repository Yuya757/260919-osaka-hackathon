/** S-05 設定 */
import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppState'
import { loadHomeStation, saveHomeStation } from '../lib/homeStation'
import { loadProfile, summarizeProfile } from '../lib/profile'
import { ACCOUNT_NAME_MAX, logOut, resizeAvatar, saveAccount, type Account } from '../lib/account'
import { Avatar, useAccount, useSession } from '../components/Avatar'

/** 自分のアイコンと表示名。この端末にだけ保存する */
function AccountCard() {
  const saved = useAccount()
  const [draft, setDraft] = useState<Account>(saved)
  const [message, setMessage] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const changed = draft.name.trim() !== saved.name || draft.avatar !== saved.avatar

  const onPick = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      const avatar = await resizeAvatar(file)
      setDraft((current) => ({ ...current, avatar }))
      setMessage('')
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : '画像を読み込めませんでした。')
    }
  }

  const onSave = (event: FormEvent) => {
    event.preventDefault()
    if (!saveAccount(draft)) {
      setMessage('ブラウザに保存できませんでした。プライベートウィンドウでは保存されません。')
      return
    }
    setMessage('アイコンと名前を保存しました。')
  }

  return (
    <form className="profile-card account-card" onSubmit={onSave}>
      <div className="account-row">
        <Avatar account={draft} size="lg" />
        <div className="account-avatar-actions">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="sr-only"
            id="account-avatar"
            onChange={(event) => void onPick(event)}
          />
          <button type="button" className="button" onClick={() => fileRef.current?.click()}>
            {draft.avatar ? 'アイコンを変える' : 'アイコンを選ぶ'}
          </button>
          {draft.avatar && (
            <button
              type="button"
              className="link-button"
              onClick={() => setDraft((current) => ({ ...current, avatar: null }))}
            >
              アイコンを外す
            </button>
          )}
        </div>
      </div>
      <div className="route-form">
        <label className="sr-only" htmlFor="account-name">
          表示名
        </label>
        <input
          id="account-name"
          value={draft.name}
          placeholder="表示名（例: ゆうや）"
          maxLength={ACCOUNT_NAME_MAX}
          autoComplete="nickname"
          onChange={(event) => {
            setDraft((current) => ({ ...current, name: event.target.value }))
            setMessage('')
          }}
        />
        <button type="submit" disabled={!changed}>
          保存
        </button>
      </div>
      {message && (
        <p className="fine" role="status">
          {message}
        </p>
      )}
      <p className="fine">アイコンと名前はこの端末にだけ保存し、サーバーには送信しません。</p>
    </form>
  )
}

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
  const session = useSession()
  const { profile, notice } = loadProfile()
  const registeredCount = Object.keys(calendar).length

  return (
    <div className="settings">
      <h1>設定</h1>

      <section className="settings-section">
        <p className="eyebrow">プロフィール</p>
        <AccountCard />
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
            ログイン中（モック）
            <small>{session?.email}</small>
          </span>
          <button type="button" className="button" onClick={logOut}>
            ログアウト
          </button>
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
