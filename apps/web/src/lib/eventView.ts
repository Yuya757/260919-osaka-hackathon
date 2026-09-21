/**
 * 表示用の純粋関数。画面設計書 §3.2 / §3.3 / §3.4 の表示ルールをここに集約する。
 *
 * 重要: 日時は必ずイベントの `dates.timezone` で解釈する。端末のローカル
 * タイムゾーンで整形すると、申込締切の時刻がずれて表示される。締切の見落とし
 * を防ぐのがこのプロダクトの目的なので、そのずれは致命的。
 */
import type { Event, EventLocationType, ValidationStatus } from '../types/api'

const DAY_MS = 24 * 60 * 60 * 1000
const DEFAULT_TZ = 'Asia/Tokyo'

type Parts = { y: number; m: number; d: number; hh: string; mm: string }

function parts(iso: string, timeZone = DEFAULT_TZ): Parts {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  const found: Record<string, string> = {}
  for (const part of formatter.formatToParts(new Date(iso))) {
    found[part.type] = part.value
  }
  return {
    y: Number(found.year),
    m: Number(found.month),
    d: Number(found.day),
    hh: found.hour,
    mm: found.minute,
  }
}

/** 「M月D日」 */
export function formatDate(iso: string, timeZone?: string): string {
  const p = parts(iso, timeZone)
  return `${p.m}月${p.d}日`
}

/** 「HH:mm」 */
export function formatTime(iso: string, timeZone?: string): string {
  const p = parts(iso, timeZone)
  return `${p.hh}:${p.mm}`
}

/** カレンダーの索引に使う暦日キー */
export function dayKey(iso: string, timeZone?: string): string {
  const p = parts(iso, timeZone)
  return `${p.y}-${p.m}-${p.d}`
}

/** そのタイムゾーンでの暦日を表す通し番号 */
export function dayIndex(iso: string, timeZone?: string): number {
  const p = parts(iso, timeZone)
  return Date.UTC(p.y, p.m - 1, p.d) / DAY_MS
}

/** ローカルのDateとして暦日を得る（月グリッドの突き合わせ用） */
export function dayDate(iso: string, timeZone?: string): Date {
  const p = parts(iso, timeZone)
  return new Date(p.y, p.m - 1, p.d)
}

/**
 * 申込締切のラベル。
 * `null` は必ず「未確認」。**「締切なし」と表現してはならない**（§6.6）。
 * 精度が 'date' のときは時刻を出さない（「23:59」を捏造しない）。
 */
export function deadlineLabel(event: Event): string {
  const iso = event.dates.applicationDeadline
  if (!iso) return '未確認'
  const tz = event.dates.timezone
  if (event.dates.applicationDeadlinePrecision === 'date') return formatDate(iso, tz)
  return `${formatDate(iso, tz)} ${formatTime(iso, tz)}`
}

/** 開催日のラベル。複数日開催は「M月D日 — M月D日」。 */
export function heldLabel(event: Event): string {
  const { eventStart, eventEnd, timezone } = event.dates
  if (eventEnd && dayKey(eventEnd, timezone) !== dayKey(eventStart, timezone)) {
    return `${formatDate(eventStart, timezone)} — ${formatDate(eventEnd, timezone)}`
  }
  const base = formatDate(eventStart, timezone)
  return event.dates.eventStartPrecision === 'date'
    ? base
    : `${base} ${formatTime(eventStart, timezone)}`
}

/** 残り日数。暦日どうしの差で数え、時刻の端数で1日ずれないようにする。 */
export function daysUntil(iso: string | null | undefined, timeZone?: string): number | null {
  if (!iso) return null
  return dayIndex(iso, timeZone) - dayIndex(new Date().toISOString(), timeZone)
}

export function relativeLabel(
  iso: string | null | undefined,
  kind: 'left' | 'after',
  timeZone?: string,
): string {
  const n = daysUntil(iso, timeZone)
  if (n === null) return ''
  if (n < 0) return '終了'
  if (n === 0) return '今日'
  return kind === 'left' ? `あと${n}日` : `${n}日後`
}

/** 締切が不明なイベントを「締切間近」にしてはならない（§3.4） */
export function isUrgent(event: Event, thresholdDays = 5): boolean {
  const n = daysUntil(event.dates.applicationDeadline, event.dates.timezone)
  return n !== null && n >= 0 && n <= thresholdDays
}

export function isFinished(event: Event): boolean {
  const end = event.dates.eventEnd ?? event.dates.eventStart
  const n = daysUntil(end, event.dates.timezone)
  return n !== null && n < 0
}

/** 申込締切と開催日のあいだの日数。締切が不明なら null。 */
export function gapDays(event: Event): number | null {
  const { applicationDeadline, eventStart, timezone } = event.dates
  if (!applicationDeadline) return null
  return dayIndex(eventStart, timezone) - dayIndex(applicationDeadline, timezone)
}

export function formatLocationType(type: EventLocationType): string {
  if (type === 'online') return 'オンライン'
  if (type === 'hybrid') return 'ハイブリッド'
  if (type === 'offline') return '会場'
  return '形式未確認'
}

export function placeLabel(event: Event): string {
  return event.location.venue || event.location.region || '場所未確認'
}

/**
 * カテゴリの表示名。バックエンドは識別子を英語で持つので、ここで日本語にする
 * （AGENTS.md: identifiers are English, user-facing copy is Japanese）。
 * 未知の識別子はそのまま出す。
 */
const CATEGORY_LABEL: Record<string, string> = {
  hackathon: 'ハッカソン',
  conference: 'カンファレンス',
  meetup: 'ミートアップ',
  acceleration: 'アクセラレーター',
  pitch: 'ピッチ',
  workshop: 'ワークショップ',
  seminar: 'セミナー',
  other: 'その他',
}

export function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category] ?? category
}

/**
 * 通常UIへ出してよいイベントだけを残す（§8.3）。
 * サーバ側でも絞っているが、UI側でも落として二重の防御にする。
 */
export function displayable(events: Event[]): Event[] {
  return events.filter(
    (event) => event.validationStatus === 'verified' || event.validationStatus === 'partial',
  )
}

export function validationLabel(status: ValidationStatus): string {
  return status === 'verified' ? '公式情報で確認済み' : '一部未確認'
}

/** `partial` のイベントで何が欠けているかを列挙する。§6.6 により明示が必要。 */
export function missingFields(event: Event): string[] {
  const missing: string[] = []
  if (!event.dates.applicationDeadline) missing.push('申込締切')
  if (!event.organizer) missing.push('主催者')
  if (event.location.type === 'unknown') missing.push('開催形式')
  if (!event.location.venue && !event.location.region) missing.push('開催場所')
  return missing
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

/** 締切だけをカレンダーに登録できるか。不明な締切を推測登録してはならない。 */
export function canRegisterDeadline(event: Event): boolean {
  return Boolean(event.dates.applicationDeadline)
}

export function isCalendarRegistered(ids?: {
  deadlineEventId?: string | null
  mainEventId?: string | null
}): boolean {
  return Boolean(ids?.deadlineEventId || ids?.mainEventId)
}
