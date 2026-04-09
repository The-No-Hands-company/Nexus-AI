const CACHE = 'nexus-ai-v3';
const PRECACHE = ['/', '/static/manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // Network-first for API calls AND HTML pages — always get fresh UI
  if (e.request.url.includes('/agent') || e.request.url.includes('/session') ||
      e.request.url.includes('/chats') || e.request.url.includes('/providers') ||
      e.request.headers.get('accept')?.includes('text/html')) {
    return;
  }
  // Cache-first only for static assets (JS libs, icons, manifest)
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(resp => {
        if (resp.ok && e.request.method === 'GET') {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      });
    }).catch(() => caches.match('/'))
  );
});
