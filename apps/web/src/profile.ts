export const prefectures = '北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県'.split(' ')
// 要件定義書 §2.1 のターゲット（エンジニア、ハッカソン参加者、起業準備者、
// 登壇機会を探すスピーカー）に合わせる。評価データセットとデモカタログの
// category（hackathon / meetup / conference / pitch / acceleration）に対応する。
// 生活系ジャンル（音楽・食事）は v3 で廃止した（画面設計書§8-5）。
export const genres = [
  'ハッカソン',
  '勉強会・ミートアップ',
  'カンファレンス',
  'LT・登壇',
  'ピッチ・アクセラレータ',
]
export const profileStorageKey = 'event-agent-profile-v2'

// v2 の選択値から v3 の選択肢への読み替え。対応先が無いものは捨てる。
const genresV2ToV3: Record<string, string> = {
  ハッカソン: 'ハッカソン',
  勉強会: '勉強会・ミートアップ',
}

export type Profile = {
  version: 3
  prefecture: string
  city: string
  distance: number
  walkMinutes: number
  online: boolean
  genres: string[]
  keywords: string
  excluded: string
  snsInterests: string
}

export const emptyProfile: Profile = {
  version: 3, prefecture: '', city: '', distance: 27, walkMinutes: 10,
  online: false, genres: [], keywords: '', excluded: '', snsInterests: '',
}

function validChoices(value: unknown, allowed: string[]): value is string[] {
  return Array.isArray(value) && value.length <= allowed.length &&
    new Set(value).size === value.length && value.every(item => typeof item === 'string' && allowed.includes(item))
}

export function isProfile(value: unknown): value is Profile {
  if (!value || typeof value !== 'object') return false
  const p = value as Record<string, unknown>
  return p.version === 3 && typeof p.prefecture === 'string' && prefectures.includes(p.prefecture) &&
    typeof p.city === 'string' && p.city.length <= 60 &&
    typeof p.distance === 'number' && Number.isInteger(p.distance) && p.distance >= 1 && p.distance <= 1000 &&
    typeof p.walkMinutes === 'number' && Number.isInteger(p.walkMinutes) && p.walkMinutes >= 1 && p.walkMinutes <= 120 &&
    typeof p.online === 'boolean' && validChoices(p.genres, genres) && p.genres.length > 0 &&
    typeof p.keywords === 'string' && p.keywords.length <= 300 &&
    typeof p.excluded === 'string' && p.excluded.length <= 200 &&
    typeof p.snsInterests === 'string' && p.snsInterests.length <= 300
}

/** v2 で保存された内容を v3 の形へ読み替える。ジャンルが1つも残らなければ諦める。 */
function migrateFromV2(value: Record<string, unknown>): Profile | null {
  if (value.version !== 2) return null
  const previous = Array.isArray(value.genres) ? value.genres : []
  const mapped = [...new Set(
    previous.flatMap(item => (typeof item === 'string' && genresV2ToV3[item] ? [genresV2ToV3[item]] : [])),
  )]
  if (mapped.length === 0) return null
  const { meals: _discarded, ...rest } = value
  const candidate = { ...rest, version: 3, genres: mapped }
  return isProfile(candidate) ? candidate : null
}

export function loadProfile(): { profile: Profile | null; notice: string } {
  try {
    const raw = localStorage.getItem(profileStorageKey)
    if (!raw) return { profile: null, notice: '' }
    const value: unknown = JSON.parse(raw)
    if (isProfile(value)) return { profile: value, notice: '' }
    if (value && typeof value === 'object') {
      const migrated = migrateFromV2(value as Record<string, unknown>)
      if (migrated) {
        return { profile: migrated, notice: '興味のあるジャンルの選択肢を見直しました。設定を確認してください。' }
      }
    }
    return { profile: null, notice: '保存内容を読み込めませんでした。プロフィールを設定し直してください。' }
  } catch {
    return { profile: null, notice: 'ブラウザの保存内容を読み込めませんでした。このページ内でプロフィールを設定できます。' }
  }
}
