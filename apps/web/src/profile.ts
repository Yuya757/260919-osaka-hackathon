export const prefectures = '北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県'.split(' ')
export const genres = ['音楽', '食事', 'ハッカソン', '勉強会']
export const meals = ['ランチ', 'ディナー']
export const profileStorageKey = 'event-agent-profile-v2'

export type Profile = {
  version: 2
  prefecture: string
  city: string
  distance: number
  walkMinutes: number
  online: boolean
  genres: string[]
  meals: string[]
  keywords: string
  excluded: string
  snsInterests: string
}

export const emptyProfile: Profile = {
  version: 2, prefecture: '', city: '', distance: 27, walkMinutes: 10,
  online: false, genres: [], meals: [], keywords: '', excluded: '', snsInterests: '',
}

function validChoices(value: unknown, allowed: string[]): value is string[] {
  return Array.isArray(value) && value.length <= allowed.length &&
    new Set(value).size === value.length && value.every(item => typeof item === 'string' && allowed.includes(item))
}

export function isProfile(value: unknown): value is Profile {
  if (!value || typeof value !== 'object') return false
  const p = value as Record<string, unknown>
  return p.version === 2 && typeof p.prefecture === 'string' && prefectures.includes(p.prefecture) &&
    typeof p.city === 'string' && p.city.length <= 60 &&
    typeof p.distance === 'number' && Number.isInteger(p.distance) && p.distance >= 1 && p.distance <= 1000 &&
    typeof p.walkMinutes === 'number' && Number.isInteger(p.walkMinutes) && p.walkMinutes >= 1 && p.walkMinutes <= 120 &&
    typeof p.online === 'boolean' && validChoices(p.genres, genres) && p.genres.length > 0 &&
    validChoices(p.meals, meals) && (p.genres.includes('食事') ? p.meals.length > 0 : p.meals.length === 0) &&
    typeof p.keywords === 'string' && p.keywords.length <= 300 &&
    typeof p.excluded === 'string' && p.excluded.length <= 200 &&
    typeof p.snsInterests === 'string' && p.snsInterests.length <= 300
}

export function loadProfile(): { profile: Profile | null; notice: string } {
  try {
    const raw = localStorage.getItem(profileStorageKey)
    if (!raw) return { profile: null, notice: '' }
    const value: unknown = JSON.parse(raw)
    if (isProfile(value)) return { profile: value, notice: '' }
    return { profile: null, notice: '保存内容を読み込めませんでした。プロフィールを設定し直してください。' }
  } catch {
    return { profile: null, notice: 'ブラウザの保存内容を読み込めませんでした。このページ内でプロフィールを設定できます。' }
  }
}
