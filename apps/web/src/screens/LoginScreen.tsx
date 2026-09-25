/**
 * ログイン（モック）。認証はまだ無いので、メールアドレスと表示名だけで入る。
 * パスワードも本人確認も無い。利用者 ID はメールアドレスから決まり、
 * 「N人が登録」で同じ人を 2 回数えないための目印にだけ使う。
 */
import { useState, type FormEvent } from 'react'
import { ACCOUNT_NAME_MAX, isValidEmail, logIn } from '../lib/account'

const DEMO_EMAIL = 'demo@example.com'

export function LoginScreen() {
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')

  const enter = async (address: string, displayName: string) => {
    if (!isValidEmail(address)) {
      setError('メールアドレスの形で入力してください。')
      return
    }
    setPending(true)
    setError('')
    try {
      if (!(await logIn(address, displayName || address.split('@')[0]))) {
        setError('ブラウザに保存できませんでした。プライベートウィンドウではログインできません。')
      }
    } catch {
      setError('ログインできませんでした。')
    } finally {
      setPending(false)
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    void enter(email, name)
  }

  return (
    <main className="login">
      <div className="login-card">
        <p className="login-brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          超イベント管理
        </p>
        <h1>ログイン</h1>
        <p className="sheet-warn">⚠ デモ用のモックです。パスワードは要りません。</p>
        <form className="login-form" onSubmit={onSubmit}>
          <label htmlFor="login-email">メールアドレス</label>
          <input
            id="login-email"
            type="email"
            inputMode="email"
            autoComplete="email"
            value={email}
            placeholder="you@example.com"
            onChange={(event) => {
              setEmail(event.target.value)
              setError('')
            }}
          />
          <label htmlFor="login-name">表示名（あとで設定から変えられます）</label>
          <input
            id="login-name"
            autoComplete="nickname"
            maxLength={ACCOUNT_NAME_MAX}
            value={name}
            placeholder="例: ゆうや"
            onChange={(event) => setName(event.target.value)}
          />
          {error && (
            <p className="fine warn" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="button button-primary wide" disabled={pending || !email.trim()}>
            {pending ? 'ログインしています…' : 'ログイン'}
          </button>
        </form>
        <button
          type="button"
          className="button wide"
          disabled={pending}
          onClick={() => void enter(DEMO_EMAIL, 'デモユーザー')}
        >
          デモ用アカウントで試す
        </button>
        <p className="fine">
          メールアドレスはこの端末にだけ保存します。サーバーには、メールアドレスから作った利用者 ID
          （カレンダー登録の人数を数えるための目印）だけを送ります。
        </p>
      </div>
    </main>
  )
}
