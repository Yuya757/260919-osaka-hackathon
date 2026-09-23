/**
 * プロフィール（興味・条件）。カード式ステップで選ぶチップの集合として持つ。
 *
 * v3 までは都道府県セレクトや距離・徒歩分のフォームだったが、簡素化UIで
 * 「行ける範囲」「ジャンル」「目的」「得意な技術」「参加しやすい日時」の
 * 5ステップのチップ選択に置き換えた。この端末の localStorage にだけ保存し、
 * サーバーには送らない。v6 で「行ける範囲」を関西の府県から全国の地方区分に広げた。
 */

export type ProfileGroup = 'area' | 'hackathonTypes' | 'purposes' | 'skills' | 'availability'

export type ProfileStep = {
  key: ProfileGroup
  title: string
  help: string
  /** false のときは1つだけ選べる */
  multi: boolean
  options: string[]
}

// 要件定義書 §2.1 のターゲット（エンジニア、ハッカソン参加者、起業準備者、
// 登壇機会を探すスピーカー）に合わせる。ジャンルは評価データセットとデモ
// カタログの category（hackathon / meetup / conference / pitch / acceleration）に対応する。
export const profileSteps: ProfileStep[] = [
  {
    key: 'area',
    title: 'どのあたりなら行けますか',
    help: 'いくつでも選べます。あとから変えられます。',
    multi: true,
    options: [
      '北海道・東北',
      '関東',
      '中部',
      '関西',
      '中国・四国',
      '九州・沖縄',
      '全国どこでも',
      'オンラインだけ',
    ],
  },
  {
    key: 'hackathonTypes',
    title: 'どんなハッカソンに出たいですか',
    help: 'いくつでも選べます。',
    multi: true,
    options: ['学生・初心者歓迎', 'ビジネス・起業', '技術特化', 'オンライン参加OK'],
  },
  {
    key: 'purposes',
    title: '参加する目的は',
    help: '推薦の並び順に使います。',
    multi: true,
    options: [
      '技術を学ぶ',
      '仲間・チームを探す',
      '登壇して知ってもらう',
      '仕事・案件につなげる',
      '資金調達の情報を集める',
      'とにかく手を動かす',
    ],
  },
  {
    key: 'skills',
    title: '得意なこと・興味のある技術',
    help: 'タグで選ぶと、近いテーマのイベントが上に来ます。',
    multi: true,
    options: [
      '生成AI',
      'GCP',
      'AWS',
      'Python',
      'TypeScript',
      'Rust',
      'Go',
      'モバイル',
      'データ基盤',
      'デザイン',
      'プロダクト企画',
      '初心者歓迎',
    ],
  },
  {
    key: 'availability',
    title: '参加しやすいのはいつ',
    help: '締切より先に、行ける日かどうかで並べ替えます。',
    multi: true,
    options: ['平日の夜', '土曜', '日曜', '平日の日中', '連休', 'いつでも'],
  },
]

export type Profile = { version: 6 } & Record<ProfileGroup, string[]>

export const emptyProfile: Profile = {
  version: 6,
  area: [],
  hackathonTypes: [],
  purposes: [],
  skills: [],
  availability: [],
}

// キー名は v2 から据え置き。中身の version で世代を判定する。
export const profileStorageKey = 'event-agent-profile-v2'

function validChoices(value: unknown, step: ProfileStep): value is string[] {
  if (!Array.isArray(value)) return false
  if (!step.multi && value.length > 1) return false
  return (
    new Set(value).size === value.length &&
    value.every((item) => typeof item === 'string' && step.options.includes(item))
  )
}

export function isProfile(value: unknown): value is Profile {
  if (!value || typeof value !== 'object') return false
  const p = value as Record<string, unknown>
  if (p.version !== 6) return false
  return profileSteps.every((step) => validChoices(p[step.key], step))
}

/** 選択肢に無い値を落として、必ず保存できる形に整える。 */
export function sanitizeProfile(value: Profile): Profile {
  const next: Profile = { ...emptyProfile }
  for (const step of profileSteps) {
    const picked = value[step.key].filter((item) => step.options.includes(item))
    next[step.key] = step.multi ? [...new Set(picked)] : picked.slice(0, 1)
  }
  return next
}

/** v5 まで（関西の府県）の「行ける範囲」→ v6 の地方区分 */
const LEGACY_AREA: Record<string, string> = {
  大阪府: '関西',
  京都府: '関西',
  兵庫県: '関西',
  奈良県: '関西',
  関西どこでも: '関西',
  オンラインだけ: 'オンラインだけ',
}

function migrateArea(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  const mapped = raw
    .map((item) => (typeof item === 'string' ? LEGACY_AREA[item] : undefined))
    .filter((item): item is string => Boolean(item))
  return [...new Set(mapped)]
}

/**
 * v5（関西の府県から 1 つ）からの読み替え。「行ける範囲」を地方区分に直し、
 * ほかの項目はそのまま引き継ぐ。
 */
function migrateFromV5(value: Record<string, unknown>): Profile | null {
  if (value.version !== 5) return null
  const candidate: Profile = { ...emptyProfile }
  for (const step of profileSteps) {
    const raw = value[step.key]
    if (step.key === 'area') {
      candidate.area = migrateArea(raw)
    } else if (Array.isArray(raw)) {
      candidate[step.key] = raw.filter(
        (item): item is string => typeof item === 'string' && step.options.includes(item),
      )
    }
  }
  return isProfile(candidate) ? candidate : null
}

/** v3（都道府県・距離・フォーム式）からの読み替え。対応先が無い項目は捨てる。 */
function migrateFromV3(value: Record<string, unknown>): Profile | null {
  if (value.version !== 3) return null
  const prefecture = typeof value.prefecture === 'string' ? value.prefecture : ''
  const online = value.online === true
  const area = LEGACY_AREA[prefecture]
    ? [LEGACY_AREA[prefecture]]
    : online && !prefecture
      ? ['オンラインだけ']
      : ['関西']
  const candidate: Profile = { ...emptyProfile, area }
  return isProfile(candidate) ? candidate : null
}

/**
 * v4（ジャンル選択あり）からの読み替え。ハッカソンに絞ったので「ジャンル」は捨て、
 * 行ける範囲・目的・技術・日時はそのまま引き継ぐ。
 */
function migrateFromV4(value: Record<string, unknown>): Profile | null {
  if (value.version !== 4) return null
  const candidate: Profile = { ...emptyProfile }
  for (const step of profileSteps) {
    if (step.key === 'hackathonTypes') continue
    const raw = value[step.key]
    if (step.key === 'area') {
      candidate.area = migrateArea(raw)
    } else if (Array.isArray(raw)) {
      candidate[step.key] = raw.filter(
        (item): item is string => typeof item === 'string' && step.options.includes(item),
      )
    }
  }
  return isProfile(candidate) ? candidate : null
}

export function loadProfile(): { profile: Profile | null; notice: string } {
  try {
    const raw = localStorage.getItem(profileStorageKey)
    if (!raw) return { profile: null, notice: '' }
    const value: unknown = JSON.parse(raw)
    if (isProfile(value)) return { profile: value, notice: '' }
    if (value && typeof value === 'object') {
      const record = value as Record<string, unknown>
      const migrated = migrateFromV5(record) ?? migrateFromV4(record) ?? migrateFromV3(record)
      if (migrated) {
        return {
          profile: migrated,
          notice: '興味の選び方が新しくなりました。内容を確認してください。',
        }
      }
    }
    return {
      profile: null,
      notice: '保存内容を読み込めませんでした。興味を設定し直してください。',
    }
  } catch {
    return {
      profile: null,
      notice: 'ブラウザの保存内容を読み込めませんでした。興味はこのページ内で設定できます。',
    }
  }
}

/** 保存に成功したら true。プライベートウィンドウ等では失敗することがある。 */
export function saveProfile(profile: Profile): boolean {
  try {
    localStorage.setItem(profileStorageKey, JSON.stringify(sanitizeProfile(profile)))
    return true
  } catch {
    return false
  }
}

/** 設定画面の1行要約。「関西・関東 / 学生・初心者歓迎 / 技術を学ぶ / …」 */
export function summarizeProfile(profile: Profile): string {
  return profileSteps
    .map((step) => profile[step.key].join('・'))
    .filter(Boolean)
    .join(' / ')
}
