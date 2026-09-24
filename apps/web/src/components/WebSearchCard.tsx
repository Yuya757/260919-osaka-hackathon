/**
 * 利用者ごとの Web 検索の結果（ADR-014）。
 *
 * Google 検索グラウンディングの答えは、質問した本人にだけ、Search Suggestions と一緒に
 * 見せる。規約に合わせて:
 * - Search Suggestions の HTML は無改変で出す（スクリプトを動かさない iframe に入れる）
 * - 出典は計測のリダイレクトを通さずにそのままリンクする
 * - 保存・カレンダー登録・ページ登録のボタンは付けない（出典を読み込み先に回さない）
 * - 結果は画面のメモリにだけ持ち、端末にも一覧にも残さない
 */
import { useEffect, useRef, useState } from 'react'
import type { WebSearchResponse } from '../types/api'

function SearchSuggestions({ html }: { html: string }) {
  const frame = useRef<HTMLIFrameElement>(null)
  const [height, setHeight] = useState(56)
  // 中身の高さに合わせる（同じオリジン扱いにしないので、読み込み時に一度だけ測れる範囲で）
  useEffect(() => {
    const element = frame.current
    if (!element) return
    const onLoad = () => {
      try {
        const body = element.contentDocument?.body
        if (body) setHeight(Math.min(160, body.scrollHeight + 8))
      } catch {
        // 測れなければ既定の高さのまま
      }
    }
    element.addEventListener('load', onLoad)
    return () => element.removeEventListener('load', onLoad)
  }, [html])
  return (
    <iframe
      ref={frame}
      className="web-suggestions"
      title="Google 検索の候補"
      srcDoc={html}
      // スクリプトは動かさない。候補のリンクは新しいタブで Google 検索を開く
      sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
      style={{ height }}
    />
  )
}

type Props = {
  result: WebSearchResponse | null
  pending: boolean
  error: string | null
  onClose: () => void
}

export function WebSearchCard({ result, pending, error, onClose }: Props) {
  if (!result && !pending && !error) return null
  return (
    <section className="web-card" aria-live="polite">
      <div className="web-card-head">
        <p className="eyebrow">Web 検索の結果（Google 検索による AI の回答）</p>
        <button type="button" className="link-button" onClick={onClose}>
          閉じる
        </button>
      </div>
      {pending && (
        <p className="loading-line">
          <span className="spinner" aria-hidden="true" />
          <span className="shimmer">Google 検索で Web を調べています</span>
        </p>
      )}
      {error && <p className="fine warn">{error}</p>}
      {result && (
        <>
          <p className="web-answer">{result.answer}</p>
          {result.sources.length > 0 && (
            <ul className="web-sources">
              {result.sources.map((source) => (
                <li key={source.uri}>
                  <a href={source.uri} target="_blank" rel="noopener noreferrer">
                    {source.title}
                  </a>
                </li>
              ))}
            </ul>
          )}
          {result.searchEntryPointHtml && <SearchSuggestions html={result.searchEntryPointHtml} />}
          <p className="fine">
            この結果は保存されず、一覧にも追加されません。日程と申込締切は必ず公式ページでご確認ください。
          </p>
        </>
      )}
    </section>
  )
}
