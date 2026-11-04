/*
 * Receives shares from the Android share sheet (T-3.7.6.1).
 *
 * The manifest's share_target posts to /echo/share-target. This worker is
 * registered with exactly that path as its scope, so it sees that one path
 * and nothing else in the app: no API call, no page, no asset goes through it
 * and nothing is cached for reading offline (D-087's reasons for having no
 * service worker stand).
 *
 * It keeps the form as it arrived in the Cache API, which the page can also
 * read, and answers with a redirect. The shared text therefore never reaches
 * a URL, the history or a server, and it waits on this device if the user has
 * to sign in first. The page posts it and removes it. The worker holds no
 * credential: it cannot read the sign-in token and does not need one.
 *
 * shareTarget.ts reads this cache; the names below are repeated there.
 */
const CACHE = 'echo-pending-shares-v1';
const TARGET = '/echo/share-target';

self.addEventListener('install', () => {
  self.skipWaiting();
});

async function keep(request) {
  try {
    const cache = await caches.open(CACHE);
    const body = new Response(await request.blob(), {
      headers: {
        'content-type': request.headers.get('content-type') || 'multipart/form-data',
        'x-stored-at': String(Date.now()),
      },
    });
    await cache.put(`${TARGET}/pending/${crypto.randomUUID()}`, body);
    return Response.redirect(TARGET, 303);
  } catch {
    return Response.redirect(`${TARGET}?failed=1`, 303);
  }
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'POST') return;
  if (new URL(event.request.url).pathname !== TARGET) return;
  event.respondWith(keep(event.request));
});
