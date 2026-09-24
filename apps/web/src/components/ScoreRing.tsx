/** 適合度（0〜100）を円で見せる。一覧の行の右上に置く */

// 円周がちょうど 100 になる半径。strokeDasharray にスコアをそのまま渡せる
const RADIUS = 100 / (2 * Math.PI)

export function ScoreRing({ score }: { score: number }) {
  const value = Math.max(0, Math.min(100, Math.round(score)))
  return (
    <div className="score-ring" role="img" aria-label={`適合度 ${value}（100点満点）`}>
      <svg viewBox="0 0 36 36" aria-hidden="true">
        <circle className="score-ring-track" cx="18" cy="18" r={RADIUS} />
        <circle
          className="score-ring-value"
          cx="18"
          cy="18"
          r={RADIUS}
          strokeDasharray={`${value} 100`}
        />
      </svg>
      <span className="score-ring-text" aria-hidden="true">
        <strong>{value}</strong>
        <small>適合</small>
      </span>
    </div>
  )
}
