/**
 * 最寄駅（自宅や職場の駅）。経路検索の出発駅の既定値に使う。
 *
 * プロフィールと同じく、この端末の localStorage にだけ保存しサーバーには送らない。
 * キーは経路パネルが出発駅を覚えていたときのものを引き継ぐ。
 */

const HOME_STATION_KEY = 'event-agent.origin-station'

/** 読めなければ空文字。プライベートウィンドウ等では storage が使えないことがある */
export function loadHomeStation(): string {
  try {
    return window.localStorage.getItem(HOME_STATION_KEY) || ''
  } catch {
    return ''
  }
}

/** 保存に成功したら true。空文字を渡すと登録を消す */
export function saveHomeStation(value: string): boolean {
  try {
    const trimmed = value.trim().replace(/駅$/, '')
    if (trimmed) window.localStorage.setItem(HOME_STATION_KEY, trimmed)
    else window.localStorage.removeItem(HOME_STATION_KEY)
    return true
  } catch {
    return false
  }
}
