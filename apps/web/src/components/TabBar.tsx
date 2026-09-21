/**
 * 下部タブバー（画面設計書 §2.1）。
 * 5スロットのうち中央だけを隆起させ、エージェント起動に充てる。
 * position:fixed ではなく sticky。PCで中央420pxに収める際に破綻しないため（§5.3）。
 */
import { NavLink, useNavigate } from 'react-router-dom'
import { CalendarIcon, GearIcon, HeartIcon, HomeIcon, SparkIcon } from './Icon'

export function TabBar() {
  const navigate = useNavigate()

  return (
    <nav className="tabbar" aria-label="メインナビゲーション">
      <NavLink to="/" className="tab" end>
        <HomeIcon />
        <span>ホーム</span>
      </NavLink>
      <NavLink to="/calendar" className="tab">
        <CalendarIcon />
        <span>カレンダー</span>
      </NavLink>
      <button type="button" className="tab tab-raised" onClick={() => navigate('/agent')}>
        <span className="tab-raised-mark">
          <SparkIcon />
        </span>
        <span>エージェント</span>
      </button>
      <NavLink to="/saved" className="tab">
        <HeartIcon />
        <span>保存済み</span>
      </NavLink>
      <NavLink to="/settings" className="tab">
        <GearIcon />
        <span>設定</span>
      </NavLink>
    </nav>
  )
}
