/*
 * Receives shares from the Android share sheet (T-3.7.6.1).
 *
 * The manifest's share_target posts to /echo/share-target. This worker is
 * registered with exactly that path as its scope, and answers everything
 * there with a redirect to /echo/incoming, which is outside the scope. So no
 * document ever lives in the scope, which means no page is controlled and no
 * API call or asset goes through this worker (D-087's reasons for having no
 * service worker stand). Nothing is cached for reading offline. The app's
 * tests assert no controller on the page and after it.
 *
 * It keeps the form as it arrived in the Cache API, which the page can also
 * read. The shared text therefore never reaches a URL, the history or a
 * server, and it waits on this device if the user has to sign in first. The
 * worker holds no credential: it cannot read the sign-in token and does not
 * need one.
 *
 * Any website can post a form here, and nothing in this worker can tell that
 * from the share sheet: Sec-Fetch-Site is hidden from it, and a cross-site
 * form can send no Referer, as the share sheet does. So what is kept here is
 * only a proposal. It goes nowhere until the user has seen it on the page and
 * tapped Add to Echo.
 *
 * shareTarget.ts reads this cache; the names below are repeated there.
 */
const CACHE = 'echo-pending-shares-v1';
const TARGET = '/echo/share-target';
const PAGE = '/echo/incoming';

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
    return Response.redirect(PAGE, 303);
  } catch {
    return Response.redirect(`${PAGE}?failed=1`, 303);
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (new URL(request.url).pathname !== TARGET) return;
  if (request.method === 'POST') event.respondWith(keep(request));
  else if (request.mode === 'navigate') event.respondWith(Response.redirect(PAGE, 303));
});
