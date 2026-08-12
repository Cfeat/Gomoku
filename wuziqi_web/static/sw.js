// Service Worker for Wuziqi PWA
const CACHE = 'wuziqi-v1';
const ASSETS = [
  '/',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // Socket.IO requests bypass cache
  if (e.request.url.includes('socket.io')) return;
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
