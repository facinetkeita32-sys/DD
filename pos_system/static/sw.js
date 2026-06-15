const CACHE = 'dd-pos-assets'

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll([
      '/',
      '/manifest.json',
      '/icon-192.png',
      '/icon-512.png',
      'css/style.css'
    ]))
  )
  self.skipWaiting()
})

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== CACHE).map(k => caches.delete(k))
    ))
  )
  self.clients.claim()
})

self.addEventListener('fetch', e => {
  const { method, url } = e.request
  const u = new URL(url)

  // API and non-GET go straight to network
  if (u.pathname.startsWith('/api/') || method !== 'GET') {
    return e.respondWith(fetch(e.request))
  }

  // JS files: always network-first (never cache — avoids stale JS on deploy)
  if (u.pathname.endsWith('.js')) {
    return e.respondWith(fetch(e.request).catch(() => caches.match(e.request)))
  }

  // Everything else: cache-first
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request).then(res => {
      const clone = res.clone()
      caches.open(CACHE).then(c => c.put(e.request, clone))
      return res
    }))
  )
})
