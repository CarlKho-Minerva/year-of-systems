/* Service worker: makes the home-screen app open instantly and survive no-signal.
 *
 * Strategy is deliberately split:
 *   - App shell (html/css/js/icons): cache-first, so launch never waits on the network.
 *   - /api/state: network-first with a cache fallback, so you always see fresh data when
 *     online and the last-known data when not.
 *   - Mutations (POST): never touched. A write that appears to succeed offline but is
 *     actually lost is exactly the "silence is the bug" failure, so writes are allowed to
 *     fail loudly and the UI reports it.
 */
const VERSION = 'yos-v2';
const SHELL = ['/', '/index.html', '/styles.css', '/app.js',
               '/manifest.webmanifest', '/icon-192.png', '/icon-512.png', '/icon-180.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;                  // writes go straight to the network
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/export')) return; // downloads must never be cached

  // State, the course tree, and individual lessons all read the same way: fresh when
  // online, last-known when not. This is what makes a lesson readable on a plane.
  if (url.pathname === '/api/state' || url.pathname === '/api/course'
      || url.pathname.startsWith('/api/lesson/')) {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req).then((r) => r || Response.json(
          { error: 'offline and no cached state' }, { status: 503 }))));
    return;
  }

  e.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok && res.type === 'basic') {
        const copy = res.clone();
        caches.open(VERSION).then((c) => c.put(req, copy));
      }
      return res;
    }).catch(() => caches.match('/index.html'))));
});
