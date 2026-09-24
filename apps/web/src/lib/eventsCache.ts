/**
 * 一覧の前回分をこの端末に覚えておく。ページを開いた瞬間に前回の一覧を出し、
 * 裏で取り直して差し替える（stale-while-revalidate）。
 *
 * 収集は 1 日 1 回なので、前回分でもほとんど同じ。古すぎるもの（1 日超）は使わない。
 * 端末の保存領域を食わないよう、先頭の件数だけを持つ。
 */
import type { Event } from '../types/api'

const KEY = 'event-agent.events-cache-v1'
const MAX_EVENTS = 60
const MAX_AGE_MS = 24 * 3600_000

type Cached = { savedAt: number; lastCollectedAt: string | null; events: Event[] }

export function loadCachedEvents(): { events: Event[]; lastCollectedAt: string | null } | null {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (!raw) return null
    const cached = JSON.parse(raw) as Cached
    if (!Array.isArray(cached.events) || Date.now() - cached.savedAt > MAX_AGE_MS) return null
    return { events: cached.events, lastCollectedAt: cached.lastCollectedAt ?? null }
  } catch {
    return null
  }
}

export function saveCachedEvents(events: Event[], lastCollectedAt: string | null): void {
  try {
    const cached: Cached = {
      savedAt: Date.now(),
      lastCollectedAt,
      events: events.slice(0, MAX_EVENTS),
    }
    window.localStorage.setItem(KEY, JSON.stringify(cached))
  } catch {
    // 保存できなくても、次回は普通に読み込むだけ
  }
}
