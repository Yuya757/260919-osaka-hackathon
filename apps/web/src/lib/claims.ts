/**
 * 主催者の申請（ADR-013）をこの端末に覚えておく。
 *
 * 編集用の鍵はサーバーがハッシュしか持たないので、無くすと申請からやり直しになる。
 * 鍵はこの端末の localStorage にだけ置き、サーバーへは編集のときにだけ送る。
 */

const KEY = 'event-agent.claims-v1'

export type StoredClaim = {
  claimId: string
  /** 確認前は null。確認できたら鍵が入る */
  editToken: string | null
  code: string
  pageUrls: string[]
  expiresAt: string
  tokenExpiresAt?: string | null
}

function readAll(): Record<string, StoredClaim> {
  try {
    const raw = window.localStorage.getItem(KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, StoredClaim>) : {}
  } catch {
    return {}
  }
}

export function loadClaim(eventId: string): StoredClaim | null {
  const claim = readAll()[eventId]
  if (!claim) return null
  const limit = claim.editToken ? claim.tokenExpiresAt : claim.expiresAt
  // 期限の切れた申請は無かったことにする（鍵もサーバー側で使えない）
  if (limit && new Date(limit).getTime() <= Date.now()) return null
  return claim
}

/** 保存に成功したら true。プライベートウィンドウ等では失敗することがある */
export function saveClaim(eventId: string, claim: StoredClaim | null): boolean {
  try {
    const all = readAll()
    if (claim) all[eventId] = claim
    else delete all[eventId]
    window.localStorage.setItem(KEY, JSON.stringify(all))
    return true
  } catch {
    return false
  }
}
