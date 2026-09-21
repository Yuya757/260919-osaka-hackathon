/**
 * Googleカレンダー連携のモック（画面設計書 §4 S-07 / §1.2）。
 *
 * 実連携に差し替えるのはこのファイルだけで済むようにしてある。
 * `registerToCalendar` の戻り値は Event.googleCalendarEventIds と同じ形なので、
 * 中身を Google Calendar API 呼び出しに置き換えれば画面側は無変更で動く。
 *
 * §10.4 の human-in-the-loop: この関数はユーザーが確認ダイアログで承認した
 * 後にのみ呼ばれる。ここから勝手に呼んではならない。
 */
import type { Event, GoogleCalendarEventIds } from '../types/api'

const STORAGE_KEY = 'event-agent-calendar-mock-v1'

export type CalendarSelection = {
  deadline: boolean
  main: boolean
}

export type CalendarEntryPreview = {
  kind: 'deadline' | 'main'
  title: string
  when: string
  note: string
}

type Store = Record<string, GoogleCalendarEventIds>

function read(): Store {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Store) : {}
  } catch {
    // プライベートウィンドウ等で localStorage が使えないことがある
    return {}
  }
}

function write(store: Store): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  } catch {
    // 保存できなくても画面は動かす
  }
}

export function loadRegistrations(): Store {
  return read()
}

export function registrationFor(eventId: string): GoogleCalendarEventIds | undefined {
  return read()[eventId]
}

/** 冪等キー。実連携でも同一操作の二重登録を防ぐ（§9.3）。 */
export function idempotencyKey(
  userId: string,
  eventId: string,
  entry: 'deadline' | 'main',
): string {
  return `${userId}|${eventId}|${entry}`
}

export async function registerToCalendar(
  event: Event,
  selection: CalendarSelection,
): Promise<GoogleCalendarEventIds> {
  const store = read()
  const existing = store[event.eventId] ?? {}
  const result: GoogleCalendarEventIds = {
    deadlineEventId: selection.deadline
      ? existing.deadlineEventId ?? `mock-${idempotencyKey(event.userId, event.eventId, 'deadline')}`
      : null,
    mainEventId: selection.main
      ? existing.mainEventId ?? `mock-${idempotencyKey(event.userId, event.eventId, 'main')}`
      : null,
  }
  store[event.eventId] = result
  write(store)
  return result
}

export async function unregisterFromCalendar(eventId: string): Promise<void> {
  const store = read()
  delete store[eventId]
  write(store)
}
