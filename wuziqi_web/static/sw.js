// Service Worker for Wuziqi PWA
const CACHE = 'wuziqi-v2';
const ASSETS = [
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
  // Socket.IO 请求不走缓存
  if (e.request.url.includes('socket.io')) return;
  // 网络优先：保证 index.html 等总是最新；离线时回退到缓存
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
