const CACHE_NAME = 'kickrss-v5';
const ASSETS_TO_CACHE = [
  './',
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
          // WebKit bug: if cached response was saved with a redirected status, clean it
          if (cachedResponse.redirected) {
            return cleanRedirectedResponse(cachedResponse);
          }
          return cachedResponse;
        }
        
        // Fetch from network with follow redirect option for navigation
        const fetchRequest = (e.request.mode === 'navigate')
          ? new Request(e.request, { redirect: 'follow' })
          : e.request;

        return fetch(fetchRequest).then((networkResponse) => {
          const isRedirected = networkResponse.redirected || 
                               networkResponse.type === 'opaqueredirect' || 
                               (networkResponse.status >= 300 && networkResponse.status < 400);

          if (isRedirected) {
            if (e.request.mode === 'navigate') {
              // Navigation requests: redirect client-side to strip Safari redirection metadata
              const redirectUrl = networkResponse.url || e.request.url;
              return new Response(
                `<script>window.location.replace("${redirectUrl}");</script>`,
                { headers: { 'Content-Type': 'text/html' } }
              );
            } else {
              // Static asset requests: clean it
              return cleanRedirectedResponse(networkResponse);
            }
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
  return response.blob().then((blob) => {
    return new Response(blob, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers
    });
  });
}
