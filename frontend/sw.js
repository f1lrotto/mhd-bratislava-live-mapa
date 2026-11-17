// Service worker of the installed app. The build (vite.config.ts) fills in PRECACHE, the app's
// JS and CSS, so each deploy installs a new worker with its own cache and drops the old one.
// Pages are network-first so a deploy shows at once; offline, the cached page opens and says the
// positions can't be loaded. The API is never cached: positions must be live.
const PRECACHE = self.__PRECACHE__
const CACHE = `mhd-${PRECACHE.version}`

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(['/', ...PRECACHE.files])).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  const url = new URL(req.url)
  if (req.method !== 'GET' || url.origin !== location.origin) return
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match('/')))
  } else if (url.pathname.startsWith('/assets/')) {
    // Hashed, immutable files; fonts are cached as the page first asks for them.
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ??
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone()
              event.waitUntil(caches.open(CACHE).then((c) => c.put(req, copy)))
            }
            return res
          }),
      ),
    )
  }
})
