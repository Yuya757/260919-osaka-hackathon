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

/** 「行ける範囲」→ 地域文字列に含まれていてほしい語 */
const AREA_WORDS: Record<string, string[]> = {
  大阪府: ['大阪', '梅田', '難波', 'なんば', '本町', '中之島', 'osaka'],
  京都府: ['京都', 'kyoto'],
  兵庫県: ['兵庫', '神戸', 'kobe'],
  奈良県: ['奈良', 'nara'],
  関西どこでも: ['関西', '大阪', '京都', '兵庫', '神戸', '奈良', '滋賀', '和歌山', 'kansai', 'osaka', 'kyoto', 'kobe'],
}

/**
 * 投稿がプロフィールのどの項目に合うかを返す。空なら「関心に合う」を出さない。
 * 一致した項目名をそのまま表示に使う（例: 「ハッカソン」「生成AI」「大阪府」）。
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
  const area = profile.area[0]
  if (area === 'オンラインだけ') {
    if (event.location.type === 'online' || event.location.type === 'hybrid') hits.push(area)
  } else if (area) {
    const region = `${event.location.region ?? ''} ${event.location.venue ?? ''}`.toLowerCase()
    if ((AREA_WORDS[area] ?? []).some((word) => region.includes(word))) hits.push(area)
  }
  return [...new Set(hits)]
}

export function originLabel(post: OrganizerPost): string {
  return post.origin === 'bot' ? 'ボット投稿' : '主催者投稿'
}

export function placementLabel(post: OrganizerPost): string | null {
  if (post.placement.kind === 'pinned') return '固定'
  if (post.placement.kind === 'priority') return '優先'
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
