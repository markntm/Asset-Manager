const CACHE = 'fintrack-v1';   // bump this whenever responsive.css or an icon changes
const ASSETS = ['/responsive.css', '/static/offline.html',
    '/static/icons/icon-192.png', '/static/icons/icon-512.png'];

self.addEventListener('install', e => {
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
    self.skipWaiting();
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys()
            .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
            .then(() => clients.claim())
    );
});

self.addEventListener('fetch', e => {
    const req = e.request, url = new URL(req.url);
    if (req.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
    if (req.mode === 'navigate') {   // pages: always network, offline page as fallback
        e.respondWith(fetch(req).catch(() => caches.match('/static/offline.html')));
        return;
    }
    e.respondWith(caches.match(req).then(hit => hit || fetch(req)));   // static assets: cache-first
});
