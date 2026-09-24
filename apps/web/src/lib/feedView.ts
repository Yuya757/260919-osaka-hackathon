/**
 * 主催者投稿フィードの表示用純関数（F-06）。
 *
 * 関心との照合はここ（クライアント）で行う。プロフィールはこの端末の
 * localStorage にしか無く、サーバーへ送らない設計なので（ADR-006 決定7）。
 */
import type { Profile } from './profile'
import type { OrganizerPost } from '../types/api'

/** 「どんなハッカソンに出たいか」→ タイトル・本文に含まれていてほしい語 */
const HACKATHON_WORDS: Record<string, string[]> = {
  '学生・初心者歓迎': ['学生', '初心者', 'ビギナー', '未経験', 'student'],
  'ビジネス・起業': ['ビジネス', '起業', 'スタートアップ', 'startup', '事業'],
  技術特化: ['api', 'ai', '生成ai', 'llm', 'データ', 'クラウド', 'gcp', 'aws', '開発者'],
}

/** 「行ける範囲」（地方区分）→ 地域文字列に含まれていてほしい語。都道府県名と主な都市 */
const AREA_WORDS: Record<string, string[]> = {
  '北海道・東北': [
    '北海道', '札幌', '青森', '岩手', '盛岡', '宮城', '仙台', '秋田', '山形', '福島', '郡山',
    '東北', 'hokkaido', 'sapporo', 'sendai', 'tohoku',
  ],
  関東: [
    '東京', '渋谷', '新宿', '品川', '六本木', '秋葉原', '神奈川', '横浜', '川崎', '埼玉', '千葉',
    '茨城', 'つくば', '栃木', '宇都宮', '群馬', '高崎', '関東', 'tokyo', 'yokohama', 'kanto',
  ],
  中部: [
    '愛知', '名古屋', '静岡', '浜松', '岐阜', '三重', '新潟', '長野', '富山', '石川', '金沢',
    '福井', '山梨', '甲府', '中部', '北陸', '東海', 'nagoya', 'shizuoka', 'kanazawa',
  ],
  関西: [
    '関西', '大阪', '梅田', '難波', 'なんば', '本町', '中之島', '京都', '兵庫', '神戸', '奈良',
    '滋賀', '和歌山', 'kansai', 'osaka', 'kyoto', 'kobe', 'nara',
  ],
  '中国・四国': [
    '広島', '岡山', '山口', '鳥取', '島根', '松江', '香川', '高松', '徳島', '愛媛', '松山',
    '高知', '中国地方', '四国', 'hiroshima', 'okayama', 'shikoku',
  ],
  '九州・沖縄': [
    '福岡', '博多', '天神', '北九州', '佐賀', '長崎', '熊本', '大分', '宮崎', '鹿児島', '沖縄',
    '那覇', '九州', 'fukuoka', 'kumamoto', 'okinawa', 'kyushu',
  ],
}

/**
 * 投稿がプロフィールのどの項目に合うかを返す。空なら「関心に合う」を出さない。
 * 一致した項目名をそのまま表示に使う（例: 「ハッカソン」「生成AI」「関西」）。
 */
export function profileMatches(post: OrganizerPost, profile: Profile | null): string[] {
  if (!profile) return []
  const hits: string[] = []
  const { event } = post
  const text = `${post.title}\n${post.body}`.toLowerCase()

  for (const kind of profile.hackathonTypes) {
    if (kind === 'オンライン参加OK') {
      if (event.location.type === 'online' || event.location.type === 'hybrid') hits.push(kind)
    } else if ((HACKATHON_WORDS[kind] ?? []).some((word) => text.includes(word))) {
      hits.push(kind)
    }
  }
  for (const skill of profile.skills) {
    if (text.includes(skill.toLowerCase())) hits.push(skill)
  }
  // 「東京都」は「京都」を含む。関西に当てないよう先に外す
  const region = `${event.location.region ?? ''} ${event.location.venue ?? ''}`
    .replace(/東京都/g, '東京')
    .toLowerCase()
  for (const area of profile.area) {
    if (area === 'オンラインだけ') {
      if (event.location.type === 'online' || event.location.type === 'hybrid') hits.push(area)
    } else if ((AREA_WORDS[area] ?? []).some((word) => region.includes(word))) {
      // 「全国どこでも」は語を持たないので、関心の一致としては出さない
      hits.push(area)
    }
  }
  return [...new Set(hits)]
}

export function originLabel(post: OrganizerPost): string {
  return post.origin === 'bot' ? 'ボット投稿' : '主催者投稿'
}

/** スポンサー枠（PR 枠、ADR-009）の表示。期限つきの固定は「スポンサー · 10/15まで」 */
export function placementLabel(post: OrganizerPost): string | null {
  const until = post.placement.until
    ? new Date(post.placement.until).toLocaleDateString('ja-JP', {
        timeZone: 'Asia/Tokyo',
        month: 'numeric',
        day: 'numeric',
      })
    : null
  if (post.placement.kind === 'pinned') return until ? `スポンサー · ${until}まで` : 'スポンサー'
  if (post.placement.kind === 'priority') return 'スポンサー'
  return null
}

/** 本文の冒頭。日付やURLの行は要約にならないので飛ばす。 */
export function excerpt(body: string, max = 120): string {
  const lines = body
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !/^(開催日|申込締切|会場|公式サイト|主催)[:：]/.test(line))
  const text = lines.join(' ')
  return text.length > max ? `${text.slice(0, max)}…` : text
}

export function postedAtLabel(iso: string): string {
  return new Date(iso).toLocaleDateString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    month: 'numeric',
    day: 'numeric',
  })
}

// ---- Slack 形式のタイムライン ----

const JST = 'Asia/Tokyo'

/** 投稿時刻（HH:MM） */
export function postedTimeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString('ja-JP', {
    timeZone: JST,
    hour: '2-digit',
    minute: '2-digit',
  })
}

function jstDayKey(iso: string): string {
  return new Date(iso).toLocaleDateString('sv-SE', { timeZone: JST })
}

/** 日付の区切り線。「今日」「昨日」「9月22日（月）」 */
export function dayDividerLabel(iso: string, now: Date = new Date()): string {
  const key = jstDayKey(iso)
  const today = jstDayKey(now.toISOString())
  const yesterday = jstDayKey(new Date(now.getTime() - 86_400_000).toISOString())
  if (key === today) return '今日'
  if (key === yesterday) return '昨日'
  return new Date(iso).toLocaleDateString('ja-JP', {
    timeZone: JST,
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  })
}

export type FeedDay = { key: string; label: string; posts: OrganizerPost[] }

/**
 * フィードを Slack のように並べる。PR の固定枠は上にまとめ、残りは古い順に
 * 日付ごとに束ねる（最新が一番下）。
 */
export function feedTimeline(
  posts: OrganizerPost[],
  now: Date = new Date(),
): { pinned: OrganizerPost[]; days: FeedDay[] } {
  const pinned = posts.filter((post) => post.placement.kind === 'pinned')
  const rest = posts
    .filter((post) => post.placement.kind !== 'pinned')
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.postId.localeCompare(b.postId))
  const days: FeedDay[] = []
  for (const post of rest) {
    const key = jstDayKey(post.createdAt)
    const last = days[days.length - 1]
    if (last && last.key === key) last.posts.push(post)
    else days.push({ key, label: dayDividerLabel(post.createdAt, now), posts: [post] })
  }
  return { pinned, days }
}

/** アイコンの 1 文字。英字は大文字、日本語はそのまま先頭 1 文字 */
export function avatarInitial(name: string): string {
  const trimmed = name.trim().replace(/^[「『（(【\s]+/, '')
  return (trimmed[0] ?? '?').toUpperCase()
}

/** 名前ごとに決まるアイコンの濃さ（0〜4）。同じ主催者は毎回同じ見た目になる */
export function avatarTone(name: string): number {
  let hash = 0
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return hash % 5
}

function countIn(value: string | undefined): number | null {
  if (!value) return null
  const match = value.replace(/,/g, '').match(/\d+/)
  return match ? Number(match[0]) : null
}

export type Capacity = {
  /** 定員。書かれていなければ null */
  limit: number | null
  /** 申込（参加登録）人数。書かれていなければ null */
  registered: number | null
  /** 人数を見た時点（収集した日時） */
  asOf: string | null
}

/**
 * 定員と申込人数。収集元が教えてくれたときだけ出す（推測しない）。
 * 申込人数は収集した時点の値なので、いつの値かを添える。
 */
export function capacityOf(post: OrganizerPost): Capacity | null {
  const attributes = post.event.attributes ?? {}
  const limit = countIn(attributes['定員'])
  const registered = countIn(attributes['参加登録'] ?? attributes['申込人数'] ?? attributes['参加者'])
  if (limit === null && registered === null) return null
  return { limit, registered, asOf: post.event.lastSeenAt ?? post.updatedAt ?? null }
}
