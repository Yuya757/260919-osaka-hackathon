/** 「N人が登録」。食べログの保存数のように、ほかの人の関心の目安として見せる */
import { CalendarIcon } from './Icon'

export function RegisteredCount({ count }: { count: number }) {
  if (count <= 0) return null
  return (
    <span className="registered-count" title="このアプリからカレンダーに登録した人数">
      <CalendarIcon className="registered-count-icon" />
      <strong>{count.toLocaleString('ja-JP')}</strong>人が登録
    </span>
  )
}
