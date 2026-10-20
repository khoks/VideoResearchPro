// node --test extension/tests
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  MENUS,
  SURFACE,
  checkToken,
  cleanPayload,
  errorText,
  looksLikeToken,
  normaliseServer,
  originPattern,
  postShare,
  sharePayload,
} from '../lib/echo.js';

const TAB = { url: 'https://example.org/essays/tariffs', title: 'Who pays for tariffs' };

test('normaliseServer accepts what people paste and refuses the rest', () => {
  assert.equal(normaliseServer('localhost:8000'), 'http://localhost:8000');
  assert.equal(normaliseServer(' https://echo.example.com/api/v1/ '), 'https://echo.example.com');
  assert.equal(normaliseServer('http://127.0.0.1:8001/'), 'http://127.0.0.1:8001');
  assert.equal(normaliseServer('ftp://example.org'), null);
  assert.equal(normaliseServer(''), null);
  assert.equal(normaliseServer('not a url at all'), null);
  assert.equal(originPattern('https://echo.example.com/x'), 'https://echo.example.com/*');
});

test('tokens are recognised by their prefix', () => {
  assert.ok(looksLikeToken('pec_' + 'a'.repeat(40)));
  assert.ok(!looksLikeToken('eyJhbGciOi.jwt.token'));
  assert.ok(!looksLikeToken('pec_short'));
});

test('every menu item has a payload builder', () => {
  for (const menu of MENUS) {
    const info = { menuItemId: menu.id, pageUrl: TAB.url, linkUrl: 'https://example.org/a', selectionText: 'x', srcUrl: 'https://example.org/i.png' };
    assert.ok(sharePayload(info, TAB).payload, menu.id);
  }
});

test('a page and a link are shared as URLs', () => {
  assert.deepEqual(sharePayload({ menuItemId: 'echo-page', pageUrl: TAB.url }, TAB, ' my reason ').payload, {
    url: TAB.url, annotation: 'my reason', surface: SURFACE,
  });
  assert.deepEqual(sharePayload({ menuItemId: 'echo-link', linkUrl: 'https://example.org/b' }, TAB).payload, {
    url: 'https://example.org/b', annotation: undefined, surface: SURFACE,
  });
});

test('a quote keeps the page it came from and is not marked as the user own words', () => {
  const { payload } = sharePayload({ menuItemId: 'echo-selection', selectionText: '  importers pay  ', pageUrl: TAB.url }, TAB);
  assert.deepEqual(payload, {
    text: 'importers pay', annotation: undefined, surface: SURFACE, source_url: TAB.url, source_title: TAB.title,
  });
  assert.equal('author_is_tenant' in payload, false);
});

test('an image goes as its address with the page as its source', () => {
  const { payload } = sharePayload({ menuItemId: 'echo-image', srcUrl: 'https://cdn.example.org/chart.png', pageUrl: TAB.url }, TAB);
  assert.equal(payload.url, 'https://cdn.example.org/chart.png');
  assert.equal(payload.content_type, 'image');
  assert.equal(payload.source_url, TAB.url);
});

test('things that cannot be shared say why', () => {
  assert.match(sharePayload({ menuItemId: 'echo-page', pageUrl: 'chrome://extensions' }, { url: 'chrome://extensions' }).reason, /web pages/);
  assert.match(sharePayload({ menuItemId: 'echo-image', srcUrl: 'data:image/png;base64,AAA', pageUrl: TAB.url }, TAB).reason, /embedded/);
  assert.match(sharePayload({ menuItemId: 'echo-selection', selectionText: '   ', pageUrl: TAB.url }, TAB).reason, /Nothing/);
  const { payload } = sharePayload({ menuItemId: 'echo-selection', selectionText: 'q', pageUrl: 'file:///C:/x.html' }, { url: 'file:///C:/x.html' });
  assert.equal(payload.source_url, undefined, 'a local file is not sent as a source');
});

test('cleanPayload drops empty fields', () => {
  assert.deepEqual(cleanPayload({ url: 'u', annotation: undefined, source_title: '', x: null }), { url: 'u' });
});

test('postShare sends the token and the cleaned payload, and reads errors', async () => {
  const calls = [];
  const ok = async (url, init) => {
    calls.push({ url, init });
    return { ok: true, status: 201, json: async () => ({ id: 's1' }) };
  };
  const res = await postShare(ok, 'localhost:8000', 'pec_tok', { url: 'https://a.b/', annotation: undefined, surface: SURFACE });
  assert.equal(res.ok, true);
  assert.equal(calls[0].url, 'http://localhost:8000/api/v1/echo/shares');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer pec_tok');
  assert.deepEqual(JSON.parse(calls[0].init.body), { url: 'https://a.b/', surface: SURFACE });

  const refused = async () => ({ ok: false, status: 401, json: async () => ({ detail: 'nope' }) });
  assert.match((await postShare(refused, 'localhost:8000', 'pec_tok', {})).error, /token was refused/);
  const down = async () => { throw new TypeError('Failed to fetch'); };
  assert.match((await checkToken(down, 'localhost:8000', 'pec_tok')).error, /Could not reach http:\/\/localhost:8000/);
  assert.equal((await postShare(ok, 'ftp://x', 'pec_tok', {})).ok, false);
});

test('errorText covers the statuses the server sends', () => {
  assert.match(errorText(403, null, 's'), /Studio/);
  assert.match(errorText(413, null, 's'), /Too long/);
  assert.equal(errorText(422, 'url must be http', 's'), 'url must be http');
  assert.match(errorText(500, null, 's'), /500/);
});
