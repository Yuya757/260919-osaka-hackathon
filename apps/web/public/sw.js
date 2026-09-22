/*
 * Service Worker（ADR-005）。
 *
 * キャッシュするのはアプリシェルだけ。/api/ は一切キャッシュしない。
 * 申込締切の見落としを防ぐアプリで古い一覧が出るのは致命的なので、
 * オフライン時は「最後に取得した一覧」ではなく取得失敗として扱わせる。
 *
 * - ナビゲーション（index.html）: ネットワーク優先。失敗時だけキャッシュ
 * - /assets/（ハッシュ付き）: キャッシュ優先。中身が変わればファイル名も変わる
 * - それ以外の同一オリジン GET: ネットワーク優先
 * - 他オリジン（Webフォント等）: 触らない。ブラウザの HTTP キャッシュに任せる
 */
const VERSION = 'shell-v1'
const SHELL_URL = '/index.html'

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      .then((cache) => cache.add(SHELL_URL))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, SHELL_URL))
    return
  }
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(cacheFirst(request))
    return
  }
  event.respondWith(networkFirst(request))
})

async function networkFirst(request, fallbackKey) {
  const cache = await caches.open(VERSION)
  try {
    const response = await fetch(request)
    if (response.ok) await cache.put(fallbackKey ?? request, response.clone())
    return response
  } catch (error) {
    const cached = await cache.match(fallbackKey ?? request)
    if (cached) return cached
    throw error
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(VERSION)
  const cached = await cache.match(request)
  if (cached) return cached
  const response = await fetch(request)
  if (response.ok) await cache.put(request, response.clone())
  return response
}
