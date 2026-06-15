const CACHE_NAME = 'kickrss-v3';
const ASSETS_TO_CACHE = [
  './',
  './index.html',
  './style.css',
  './app.js',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  
  // Normalize paths to check if they match our cached static assets
  const cleanPath = url.pathname.endsWith('/') ? url.pathname : url.pathname + '/';
  const isRoot = url.pathname === '/' || url.pathname === '/index.html' || cleanPath === self.location.pathname;
  
  const isStaticAsset = isRoot || ASSETS_TO_CACHE.some(asset => {
    if (asset === './' || asset === '.') return false;
    const assetUrl = new URL(asset, self.location.href);
    return url.pathname === assetUrl.pathname;
  });

  if (isStaticAsset) {
    e.respondWith(
      caches.match(e.request).then((cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }
        return fetch(e.request);
      })
    );
  }
  // All other requests (like /feeds, /entries, etc.) bypass the Service Worker
  // letting the native browser stack handle auth credentials/cookies correctly.
});
