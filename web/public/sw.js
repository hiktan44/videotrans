// videotrans PWA service worker
const CACHE = 'videotrans-v1';
const PRECACHE = ["/", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/') || url.pathname.startsWith('/webhook')) return;
  if (req.mode === 'navigate' || req.destination === 'document') {
    // navigate: network-first, offline'da cache'e dus
    e.respondWith(fetch(req).then((res) => { const cl = res.clone(); caches.open(CACHE).then((c) => c.put(req, cl)); return res; }).catch(() => caches.match(req).then((m) => m || caches.match('/'))));
    return;
  }
  if (/\.(css|js|png|svg|jpg|jpeg|webp|woff2?|ico)$/.test(url.pathname) || url.pathname.startsWith('/assets/')) {
    // statik varlik: cache-first
    e.respondWith(caches.match(req).then((m) => m || fetch(req).then((res) => { const cl = res.clone(); caches.open(CACHE).then((c) => c.put(req, cl)); return res; })));
  }
});
