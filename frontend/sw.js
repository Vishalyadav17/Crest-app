/**
 * Crest Service Worker
 * Strategy:
 *   - Shell assets (CSS, JS): cache-first, revalidate in background
 *   - /api/dashboard/bootstrap: stale-while-revalidate (max 5 min)
 *   - All other API calls: network-first
 *   - Offline: serve last-good shell + show offline banner
 */
const _v    = new URL(self.location).searchParams.get('v') || '6';
const CACHE = 'crest-' + _v;
const SHELL = [
  '/js/ws.js',
  '/js/fmt.js',
  '/js/api.js',
  '/js/state.js',
  '/js/shell.js',
  '/js/ui/m1_portfolio.js',
  '/js/ui/m2_market.js',
  '/js/ui/m3_trades.js',
  '/js/ui/m3_vault.js',
  '/js/ui/m3_swings.js',
  '/js/ui/m3_research.js',
  '/js/ui/m4_charts.js',
  '/js/ui/m5_watchlist.js',
  '/js/ui/m6_settings.js',
  '/js/ui/m7_indices.js',
  '/css/theme.css',
  '/css/base.css',
  '/css/ui.css',
  '/css/components.css',
];

self.addEventListener('install', evt => {
  // Fetch each shell asset with cache:'reload' so the precache always comes
  // from the network, never a stale HTTP-cached copy (prevents stale-JS bugs
  // where a version bump still served old modules).
  evt.waitUntil(
    caches.open(CACHE).then(c => Promise.all(
      SHELL.map(u => fetch(u, { cache: 'reload' })
        .then(r => { if (r.ok) return c.put(u, r); })
        .catch(() => {}))
    )).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', evt => {
  evt.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', evt => {
  const url = new URL(evt.request.url);

  // WS — don't intercept
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return;

  // /api/dashboard/bootstrap — stale-while-revalidate (5 min TTL)
  if (url.pathname === '/api/dashboard/bootstrap') {
    evt.respondWith(swrApi(evt.request, 300));
    return;
  }

  // Other API calls — network-first
  if (url.pathname.startsWith('/api/')) {
    evt.respondWith(networkFirst(evt.request));
    return;
  }

  // HTML pages — always network-first (auth-gated, must not serve stale)
  if (url.pathname === '/' || url.pathname.endsWith('.html')) {
    evt.respondWith(networkFirst(evt.request));
    return;
  }

  // Shell assets (JS/CSS) — cache-first
  evt.respondWith(cacheFirst(evt.request));
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    fetch(request).then(r => {
      if (r.ok) caches.open(CACHE).then(c => c.put(request, r));
    }).catch(() => {});
    return cached;
  }
  return networkFirst(request);
}

async function networkFirst(request) {
  try {
    const r = await fetch(request);
    if (r.ok) {
      const c = await caches.open(CACHE);
      c.put(request, r.clone());
    }
    return r;
  } catch(_) {
    const cached = await caches.match(request);
    return cached || new Response('{"error":"offline"}', {
      headers: {'Content-Type': 'application/json'},
      status: 503,
    });
  }
}

async function swrApi(request, maxAgeSeconds) {
  const cached = await caches.match(request);
  if (cached) {
    const age = (Date.now() - new Date(cached.headers.get('date')).getTime()) / 1000;
    if (age < maxAgeSeconds) {
      return cached;
    }
    fetch(request).then(r => {
      if (r.ok) caches.open(CACHE).then(c => c.put(request, r));
    }).catch(() => {});
    return cached;
  }
  return networkFirst(request);
}
