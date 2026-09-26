/* Service worker Lemari — cukup untuk installable + halaman offline.
   Halaman selalu dari jaringan (data harus segar), aset statis pakai cache. */
const CACHE = 'lemari-v2';
const ASET = [
  '/static/app.css',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/offline'
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASET)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((kunci) => Promise.all(kunci.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((cocok) => cocok || fetch(req).then((res) => {
        const salinan = res.clone();
        caches.open(CACHE).then((c) => c.put(req, salinan));
        return res;
      }))
    );
    return;
  }

  if (url.pathname.startsWith('/media/')) return; // foto jangan dicache di HP

  event.respondWith(
    fetch(req).catch(() => caches.match('/offline').then((r) => r || new Response('Offline', { status: 503 })))
  );
});
