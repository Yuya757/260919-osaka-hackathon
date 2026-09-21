import type { ApiEvent } from '../types/api'

export type EventCardModel = {
  id: string
  title: string
  organizer: string
  category: string
  location: string
  format: '会場' | 'オンライン' | 'ハイブリッド'
  deadline: string
  deadlineDay: string
  eventDate: string
  eventDay: string
  description: string
  match: number
  source: string
  urgent?: boolean
  /** 最寄駅。会場開催かつ駅が分かる場合のみ経路検索を出す */
  nearestStation?: string | null
}

const DAY_MS = 24 * 60 * 60 * 1000

function formatDateLabel(iso?: string | null): string {
  if (!iso) return '未確認'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '未確認'
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function relativeDay(iso?: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const diff = Math.ceil((date.getTime() - Date.now()) / DAY_MS)
  if (diff < 0) return '終了'
  if (diff === 0) return '今日'
  return `あと${diff}日`
}

function formatType(type: ApiEvent['location']['type']): EventCardModel['format'] {
  if (type === 'online') return 'オンライン'
  if (type === 'hybrid') return 'ハイブリッド'
  return '会場'
}

export const DEMO_EVENTS: EventCardModel[] = [
  {
    id: 'gemini-hack',
    title: 'Gemini API ハッカソン 2026',
    organizer: 'Google for Developers',
    category: '生成AI・ハッカソン',
    location: 'グランフロント大阪',
    format: '会場',
    deadline: '9月22日 23:59',
    deadlineDay: 'あと3日',
    eventDate: '10月11日 — 12日',
    eventDay: '22日後',
    description:
      'Gemini APIを使い、地域や暮らしの課題を解くプロトタイプを2日間で開発します。',
    match: 96,
    source: '公式サイトで確認済み',
    urgent: true,
    nearestStation: '大阪',
  },
  {
    id: 'cloud-next',
    title: 'Cloud Builders Kansai',
    organizer: 'GDG Osaka',
    category: 'GCP・カンファレンス',
    location: '梅田スカイビル',
    format: 'ハイブリッド',
    deadline: '10月02日 18:00',
    deadlineDay: 'あと13日',
    eventDate: '10月18日',
    eventDay: '29日後',
    description:
      'Cloud Run、Vertex AI、データ基盤の実践事例を関西の開発者が共有する1dayイベントです。',
    match: 91,
    source: '公式サイトで確認済み',
    nearestStation: '大阪',
  },
  {
    id: 'agent-meetup',
    title: 'AI Agent Product Meetup',
    organizer: 'Agentic Japan',
    category: 'AI Agent・ミートアップ',
    location: 'Google Meet',
    format: 'オンライン',
    deadline: '10月08日',
    deadlineDay: 'あと19日',
    eventDate: '10月09日 19:00',
    eventDay: '20日後',
    description:
      'プロダクトにAI Agentを組み込む設計、評価、運用の失敗と学びを持ち寄るオンライン勉強会です。',
    match: 88,
    source: '主催者ページで確認済み',
  },
]

export function toEventCard(event: ApiEvent): EventCardModel {
  const deadlineIso = event.dates.applicationDeadline
  const startIso = event.dates.eventStart
  const endIso = event.dates.eventEnd
  const daysLeft = deadlineIso
    ? Math.ceil((new Date(deadlineIso).getTime() - Date.now()) / DAY_MS)
    : 99

  return {
    id: event.eventId,
    title: event.title,
    organizer: event.organizer || '主催者未確認',
    category: event.category,
    location: event.location.venue || event.location.region || '場所未確認',
    format: formatType(event.location.type),
    deadline: formatDateLabel(deadlineIso),
    deadlineDay: relativeDay(deadlineIso),
    eventDate:
      endIso && endIso !== startIso
        ? `${formatDateLabel(startIso)} — ${formatDateLabel(endIso)}`
        : formatDateLabel(startIso),
    eventDay: relativeDay(startIso),
    description: event.summary,
    match: event.recommendation?.score ?? 70,
    source: event.officialUrl || '根拠付きで確認済み',
    urgent: daysLeft <= 5,
    nearestStation: event.location.nearestStation ?? null,
  }
}
