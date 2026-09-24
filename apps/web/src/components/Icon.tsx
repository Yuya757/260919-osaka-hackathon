/** インラインSVGアイコン。外部アイコンライブラリを増やさない。 */
type IconProps = { className?: string }

const base = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
}

export function CheckIcon(p: IconProps) {
  return (
    <svg {...base} {...p}>
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </svg>
  )
}

// ---- ナビゲーション ----

export function HomeIcon(p: IconProps) {
  return (
    <svg {...base} {...p}>
      <path d="M4 10.5 12 4l8 6.5" />
      <path d="M6 9v10h12V9" />
      <path d="M10 19v-5h4v5" />
    </svg>
  )
}

export function FeedIcon(p: IconProps) {
  return (
    <svg {...base} {...p}>
      <path d="M4 5.5h16v10H9l-5 4z" />
      <path d="M8 9.5h8M8 12.5h5" />
    </svg>
  )
}

export function CalendarIcon(p: IconProps) {
  return (
    <svg {...base} {...p}>
      <rect x="4" y="5.5" width="16" height="14" rx="2" />
      <path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" />
    </svg>
  )
}

export function BookmarkIcon(p: IconProps) {
  return (
    <svg {...base} {...p}>
      <path d="M7 4h10v16l-5-3.5L7 20z" />
    </svg>
  )
}

export function SettingsIcon(p: IconProps) {
  return (
    <svg {...base} {...p}>
      <path d="M5 7h9M18 7h1M5 17h1M10 17h9" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="8" cy="17" r="2" />
    </svg>
  )
}
