const CACHE_NAME = 'kickrss-v7';
const ASSETS_TO_CACHE = [
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
  // 1. Bypass Service Worker entirely for navigation requests to prevent WebKit redirection/cross-origin crashes
  if (e.request.mode === 'navigate') {
    return;
  }

  const url = new URL(e.request.url);
  
  // 2. Check if the request is for a cached static asset
  const isStaticAsset = ASSETS_TO_CACHE.some(asset => {
    const assetUrl = new URL(asset, self.location.href);
    return url.pathname === assetUrl.pathname;
  });

  if (isStaticAsset) {
    e.respondWith(
      caches.match(e.request).then((cachedResponse) => {
        if (cachedResponse) {
          // WebKit bug: if cached response was saved with a redirected status, clean it
          if (cachedResponse.redirected) {
            return cleanRedirectedResponse(cachedResponse);
          }
          return cachedResponse;
        }
        
        return fetch(e.request).then((networkResponse) => {
          if (networkResponse.redirected) {
            return cleanRedirectedResponse(networkResponse);
          }
          return networkResponse;
        }).catch(() => {
          return caches.match(e.request);
        });
      })
    );
  }
});

// Helper to strip redirected flag from a Response object (WebKit/Safari requirement)
function cleanRedirectedResponse(response) {
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers
  });
}
