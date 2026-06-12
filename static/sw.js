const CACHE_NAME = 'kickrss-v2';
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
  // We only cache GET requests
  if (e.request.method !== 'GET') return;

  const url = new URL(e.request.url);

  // For API endpoints, we always fetch from network first to ensure fresh data
  // But fallback to cache if offline
  if (url.pathname.startsWith('/feeds') || 
      url.pathname.startsWith('/entries') || 
      url.pathname.startsWith('/categories') || 
      url.pathname.startsWith('/profile') || 
      url.pathname.startsWith('/settings') || 
      url.pathname.startsWith('/search')) {
    e.respondWith(
      fetch(e.request).then((networkResponse) => {
        const isRedirected = networkResponse.redirected || 
                             networkResponse.status === 0 || 
                             networkResponse.type === 'opaqueredirect' || 
                             (networkResponse.status >= 300 && networkResponse.status < 400);
        if (isRedirected) {
          // If the API call gets redirected (e.g. to a login page because credentials expired),
          // return a clean 401 response so the browser/frontend handles it cleanly.
          return new Response('Unauthorized', {
            status: 401,
            statusText: 'Unauthorized'
          });
        }
        return networkResponse;
      }).catch(() => {
        return caches.match(e.request);
      })
    );
    return;
  }

  // For static assets, we use Stale-While-Revalidate
  e.respondWith(
    caches.match(e.request).then((cachedResponse) => {
      // Force follow redirects for navigation requests to get the correct final destination URL
      const fetchRequest = (e.request.mode === 'navigate')
        ? new Request(e.request, { redirect: 'follow' })
        : e.request;

      const fetchPromise = fetch(fetchRequest).then((networkResponse) => {
        const isRedirected = networkResponse.redirected || 
                             networkResponse.status === 0 || 
                             networkResponse.type === 'opaqueredirect' || 
                             (networkResponse.status >= 300 && networkResponse.status < 400);

        if (networkResponse && networkResponse.status === 200 && !isRedirected) {
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(e.request, networkResponse.clone());
          });
        }

        if (isRedirected) {
          if (e.request.mode === 'navigate') {
            // For navigation requests, return a clean HTML response with a redirect script
            // to strip Safari's internal redirect metadata and trigger client-side navigation.
            const redirectUrl = networkResponse.url || e.request.url;
            return new Response(
              `<script>window.location.replace("${redirectUrl}");</script>`,
              { headers: { 'Content-Type': 'text/html' } }
            );
          } else {
            // For non-navigation requests (like app.js, style.css, etc.), return a clean 401
            // to prevent WebKit (Safari) from crashing with "Response served by service worker has redirections".
            return new Response('Unauthorized', {
              status: 401,
              statusText: 'Unauthorized'
            });
          }
        }
        return networkResponse;
      }).catch(() => {
        // Ignore network errors during background update
      });
      return cachedResponse || fetchPromise;
    })
  );
});
