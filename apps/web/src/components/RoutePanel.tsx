import { useState, type FormEvent } from 'react'
import { getEventRoute } from '../api/client'
import type { RouteSummary } from '../types/api'

type RoutePanelProps = {
  eventId: string
  nearestStation: string
}

const ORIGIN_STORAGE_KEY = 'event-agent.origin-station'

function readSavedOrigin(): string {
  try {
    return window.localStorage.getItem(ORIGIN_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

function saveOrigin(value: string) {
  try {
    window.localStorage.setItem(ORIGIN_STORAGE_KEY, value)
  } catch {
    // storage unavailable (private mode etc.) — ignore
  }
}

function formatTime(iso?: string | null): string {
  if (!iso) return '--:--'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '--:--'
  return date.toLocaleTimeString('ja-JP', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Tokyo',
  })
}

function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours === 0) return `${rest}分`
  return rest === 0 ? `${hours}時間` : `${hours}時間${rest}分`
}

export function RoutePanel({ eventId, nearestStation }: RoutePanelProps) {
  const [open, setOpen] = useState(false)
  const [origin, setOrigin] = useState(readSavedOrigin)
  const [pending, setPending] = useState(false)
  const [route, setRoute] = useState<RouteSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  const search = async (event: FormEvent) => {
    event.preventDefault()
    const trimmed = origin.trim()
    if (!trimmed || pending) return

    setPending(true)
    setError(null)
    try {
      const response = await getEventRoute(eventId, trimmed)
      setRoute(response.route)
      saveOrigin(trimmed)
    } catch (cause) {
      setRoute(null)
      setError(cause instanceof Error ? cause.message : '経路を取得できませんでした。')
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="route-panel">
      <button
        type="button"
        className="route-toggle"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span aria-hidden="true">⇢</span>
        {open ? '経路を閉じる' : `会場までの経路（最寄: ${nearestStation}駅）`}
      </button>

      {open && (
        <div className="route-body">
          <form className="route-form" onSubmit={search}>
            <label className="sr-only" htmlFor={`route-origin-${eventId}`}>
              出発駅
            </label>
            <input
              id={`route-origin-${eventId}`}
              value={origin}
              placeholder="出発駅（例: 京都）"
              maxLength={40}
              disabled={pending}
              onChange={(event) => setOrigin(event.target.value)}
            />
            <span className="route-arrow" aria-hidden="true">
              →
            </span>
            <span className="route-destination">{nearestStation}</span>
            <button type="submit" disabled={pending || !origin.trim()}>
              {pending ? '検索中…' : '開始時刻に間に合う経路'}
            </button>
          </form>

          {error && (
            <p className="route-error" role="alert">
              {error}
            </p>
          )}

          {route && (
            <div className="route-result">
              <div className="route-summary">
                <strong>
                  {formatTime(route.departure)} 発 → {formatTime(route.arrival)} 着
                </strong>
                <span>{formatDuration(route.totalMinutes)}</span>
                <span>乗換 {route.transferCount}回</span>
                {route.fareYen != null && <span>¥{route.fareYen.toLocaleString('ja-JP')}</span>}
              </div>
              <ol className="route-legs">
                {route.legs.map((leg, index) => (
                  <li key={`${leg.line}-${index}`}>
                    <span className="route-leg-time">
                      {formatTime(leg.departure)}–{formatTime(leg.arrival)}
                    </span>
                    <span className="route-leg-line">{leg.line}</span>
                    <span className="route-leg-stations">
                      {leg.fromStation} → {leg.toStation}
                    </span>
                  </li>
                ))}
              </ol>
              <p className="route-credit">経路情報: 駅すぱあと API</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
