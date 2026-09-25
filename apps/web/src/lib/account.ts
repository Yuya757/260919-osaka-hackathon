/**
 * ログイン（モック）と、自分のアイコン・表示名。
 *
 * 認証はまだ入れていない。メールアドレスを入れると、それを元に利用者 ID を決めて
 * この端末に「ログイン中」として保存する。パスワードも本人確認も無いので、ID は
 * 「同じ人を 2 回数えない」ための目印に過ぎず、なりすましは防げない。
 * アイコンと表示名は利用者ごとにこの端末の localStorage に保存し、サーバーには送らない。
 * アイコンは選んだ画像を 128px 四方に縮めた data URL で持つ（localStorage の容量に収める）。
 */

export type Session = {
  userId: string
  email: string
}

export type Account = {
  name: string
  /** data:image/... の URL。未設定なら null で、名前の頭文字を出す */
  avatar: string | null
}

export const sessionStorageKey = 'event-agent-session-v1'
const accountStorageKey = 'event-agent-account-v1'
export const ACCOUNT_NAME_MAX = 30
const AVATAR_SIZE = 128

const emptyAccount: Account = { name: '', avatar: null }

/** 画面間で同じ値を見るための通知。保存・ログイン・ログアウトで上部バーも替わる */
const listeners = new Set<() => void>()

export function subscribeAccount(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function notify(): void {
  listeners.forEach((listener) => listener())
}

function isSession(value: unknown): value is Session {
  if (!value || typeof value !== 'object') return false
  const record = value as Record<string, unknown>
  return (
    typeof record.userId === 'string' &&
    /^u-[0-9a-f]{24}$/.test(record.userId) &&
    typeof record.email === 'string'
  )
}

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(sessionStorageKey)
    if (!raw) return null
    const value: unknown = JSON.parse(raw)
    return isSession(value) ? value : null
  } catch {
    return null
  }
}

export function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())
}

/** 同じメールアドレスなら、どの端末でも同じ ID になる */
async function userIdFor(email: string): Promise<string> {
  const bytes = new TextEncoder().encode(email.trim().toLowerCase())
  // crypto.subtle は https か localhost でしか使えない。LAN の IP で開いた開発時の控え
  if (!globalThis.crypto?.subtle) return `u-${fallbackHash(bytes)}`
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  const hex = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')
  return `u-${hex.slice(0, 24)}`
}

/** FNV-1a を種を変えて 3 回。暗号学的な強さは要らない（モックの目印） */
function fallbackHash(bytes: Uint8Array): string {
  return [0x811c9dc5, 0x01000193, 0x5bd1e995]
    .map((seed) => {
      let hash = seed >>> 0
      for (const byte of bytes) hash = Math.imul(hash ^ byte, 0x01000193) >>> 0
      return hash.toString(16).padStart(8, '0')
    })
    .join('')
}

/**
 * モックのログイン。成功したら true。表示名が未設定なら入力した名前を入れる。
 */
export async function logIn(email: string, name: string): Promise<boolean> {
  const session: Session = { userId: await userIdFor(email), email: email.trim() }
  try {
    localStorage.setItem(sessionStorageKey, JSON.stringify(session))
  } catch {
    return false
  }
  const current = loadAccount()
  if (!current.name && name.trim()) {
    saveAccount({ ...current, name })
  } else {
    notify()
  }
  return true
}

export function logOut(): void {
  try {
    localStorage.removeItem(sessionStorageKey)
  } catch {
    // 消せなくても画面はログイン前に戻す
  }
  notify()
}

/** 利用者ごとの保存先。ログインしていなければ null */
export function userScopedKey(base: string): string | null {
  const session = loadSession()
  return session ? `${base}:${session.userId}` : null
}

function isAccount(value: unknown): value is Account {
  if (!value || typeof value !== 'object') return false
  const record = value as Record<string, unknown>
  return (
    typeof record.name === 'string' &&
    (record.avatar === null ||
      (typeof record.avatar === 'string' && record.avatar.startsWith('data:image/')))
  )
}

export function loadAccount(): Account {
  const key = userScopedKey(accountStorageKey)
  if (!key) return emptyAccount
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return emptyAccount
    const value: unknown = JSON.parse(raw)
    return isAccount(value) ? value : emptyAccount
  } catch {
    return emptyAccount
  }
}

/** 保存に成功したら true。プライベートウィンドウ等では失敗することがある。 */
export function saveAccount(account: Account): boolean {
  const next: Account = {
    name: account.name.trim().slice(0, ACCOUNT_NAME_MAX),
    avatar: account.avatar,
  }
  const key = userScopedKey(accountStorageKey)
  if (!key) return false
  try {
    localStorage.setItem(key, JSON.stringify(next))
  } catch {
    return false
  }
  notify()
  return true
}

/** 名前の頭文字。名前も無ければ null（人の形のアイコンを出す） */
export function accountInitial(account: Account): string | null {
  const first = [...account.name.trim()][0]
  return first ? first.toUpperCase() : null
}

/** 選んだ画像を中央で正方形に切り抜き、128px の JPEG に縮める */
export function resizeAvatar(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith('image/')) {
      reject(new Error('画像ファイルを選んでください。'))
      return
    }
    const url = URL.createObjectURL(file)
    const image = new Image()
    image.onload = () => {
      URL.revokeObjectURL(url)
      const side = Math.min(image.naturalWidth, image.naturalHeight)
      const canvas = document.createElement('canvas')
      canvas.width = AVATAR_SIZE
      canvas.height = AVATAR_SIZE
      const context = canvas.getContext('2d')
      if (!context || side === 0) {
        reject(new Error('画像を読み込めませんでした。'))
        return
      }
      context.drawImage(
        image,
        (image.naturalWidth - side) / 2,
        (image.naturalHeight - side) / 2,
        side,
        side,
        0,
        0,
        AVATAR_SIZE,
        AVATAR_SIZE,
      )
      resolve(canvas.toDataURL('image/jpeg', 0.85))
    }
    image.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('画像を読み込めませんでした。'))
    }
    image.src = url
  })
}
