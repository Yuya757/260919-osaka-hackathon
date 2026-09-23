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
