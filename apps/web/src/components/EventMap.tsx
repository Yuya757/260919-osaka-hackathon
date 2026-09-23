/**
 * 会場の地図。Google マップの埋め込み（キー不要の `output=embed`）を使う。
 * 住所は検索語としてそのまま渡すだけで、座標は持たない。
 * オンライン開催や場所未確認では出さない。
 */
type Props = {
  query: string
}

export function mapsSearchUrl(query: string): string {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`
}

export function EventMap({ query }: Props) {
  return (
    <div className="map">
      <iframe
        title={`${query} の地図`}
        src={`https://www.google.com/maps?q=${encodeURIComponent(query)}&output=embed&hl=ja`}
        loading="lazy"
        referrerPolicy="no-referrer-when-downgrade"
        allowFullScreen
      />
    </div>
  )
}
