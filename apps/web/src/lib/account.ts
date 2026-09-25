/**
 * 自分のアイコンと表示名。この端末の localStorage にだけ保存し、サーバーには送らない。
 * アイコンは選んだ画像を 128px 四方に縮めた data URL で持つ（localStorage の容量に収める）。
 */

export type Account = {
  name: string
  /** data:image/... の URL。未設定なら null で、名前の頭文字を出す */
  avatar: string | null
}

export const accountStorageKey = 'event-agent-account-v1'
export const ACCOUNT_NAME_MAX = 30
const AVATAR_SIZE = 128

const emptyAccount: Account = { name: '', avatar: null }

/** 画面間で同じ値を見るための通知。保存したら上部バーのアイコンも替わる */
const listeners = new Set<() => void>()

export function subscribeAccount(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
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
  try {
    const raw = localStorage.getItem(accountStorageKey)
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
  try {
    localStorage.setItem(accountStorageKey, JSON.stringify(next))
  } catch {
    return false
  }
  listeners.forEach((listener) => listener())
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
