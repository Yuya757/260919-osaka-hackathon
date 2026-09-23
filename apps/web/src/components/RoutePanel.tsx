import { useState, type FormEvent } from 'react'
import { getEventRoute } from '../api/client'
import { loadHomeStation, saveHomeStation } from '../lib/homeStation'
import type { RouteSummary } from '../types/api'

type RoutePanelProps = {
  eventId: string
  /** イベントの最寄駅。未確認なら空文字で、到着駅は利用者に入力してもらう */
  nearestStation: string
  /** 会場名。到着駅を入力してもらうときの手がかりに出す */
  venue?: string
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

export function RoutePanel({ eventId, nearestStation, venue }: RoutePanelProps) {
  const [open, setOpen] = useState(false)
  const [origin, setOrigin] = useState(loadHomeStation)
  // 会場の最寄駅が分からない告知は多い。会場名を駅名として送っても見つからないので、
  // そのときは到着駅を利用者に入力してもらう
  const [destination, setDestination] = useState('')
  const [pending, setPending] = useState(false)
  const [route, setRoute] = useState<RouteSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const knownStation = nearestStation.trim()

  const search = async (event: FormEvent) => {
    event.preventDefault()
    const trimmed = origin.trim()
    const target = knownStation || destination.trim()
    if (!trimmed || !target || pending) return

    setPending(true)
    setError(null)
    try {
      const response = await getEventRoute(eventId, trimmed, knownStation ? undefined : target)
      setRoute(response.route)
      // 設定で最寄駅を登録していなければ、使った出発駅を次回の既定にする
      if (!loadHomeStation()) saveHomeStation(trimmed)
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
        {open
          ? '経路を閉じる'
          : knownStation
            ? `会場までの経路（最寄: ${knownStation}駅）`
            : '会場までの経路（到着駅を入力）'}
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
            {knownStation ? (
              <span className="route-destination">{knownStation}</span>
            ) : (
              <>
                <label className="sr-only" htmlFor={`route-destination-${eventId}`}>
                  到着駅
                </label>
                <input
                  id={`route-destination-${eventId}`}
                  value={destination}
                  placeholder="到着駅（例: 京橋）"
                  maxLength={40}
                  disabled={pending}
                  onChange={(event) => setDestination(event.target.value)}
                />
              </>
            )}
            <button
              type="submit"
              disabled={pending || !origin.trim() || !(knownStation || destination.trim())}
            >
              {pending ? '検索中…' : '開始時刻に間に合う経路'}
            </button>
          </form>

          {!knownStation && (
            <p className="fine route-hint">
              最寄駅は告知に書かれていませんでした。
              {venue ? `会場は「${venue}」です。` : ''}到着駅をご記入ください。
            </p>
          )}

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
