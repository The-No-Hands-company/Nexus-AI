const CACHE = 'nexus-ai-v4';
const PRECACHE = [
  '/',
  '/static/manifest.json',
  '/static/css/base.css',
  '/static/css/panels.css',
  '/static/js/api.js',
  '/static/js/utilities/ui-helpers.js',
  '/static/js/utilities/device-utils.js',
  '/static/js/utilities/settings.js',
  '/static/js/utilities/providers.js',
  '/static/js/panels/benchmark-leaderboard.js',
];

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
  const req = e.request;
  const accept = req.headers.get('accept') || '';

  // Always network for API calls.
  if (req.url.includes('/agent') || req.url.includes('/session') ||
      req.url.includes('/chats') || req.url.includes('/providers') ||
      req.url.includes('/api/') || req.url.includes('/v1/')) {
    return;
  }

  // HTML documents: network-first, but serve cached shell when offline.
  if (accept.includes('text/html')) {
    e.respondWith(
      fetch(req)
        .then(resp => {
          if (resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE).then(c => c.put(req, clone));
          }
          return resp;
        })
        .catch(() => caches.match(req).then(cached => cached || caches.match('/')))
    );
    return;
  }

  // Static assets: cache-first.
  e.respondWith(
    caches.match(req).then(cached => {
      if (cached) return cached;
      return fetch(req).then(resp => {
        if (resp.ok && req.method === 'GET') {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(req, clone));
        }
        return resp;
      });
    }).catch(() => caches.match('/'))
  );
});
