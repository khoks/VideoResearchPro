// Settings: the server address and the share token, kept in this browser
// only (chrome.storage.local, never synced).
import { DEFAULT_SERVER, checkToken, looksLikeToken, normaliseServer, originPattern } from './lib/echo.js';

const $ = (id) => document.getElementById(id);

async function load() {
  const { server, token } = await chrome.storage.local.get(['server', 'token']);
  $('server').value = server || DEFAULT_SERVER;
  $('token').value = token || '';
}

async function save() {
  const server = normaliseServer($('server').value);
  const token = $('token').value.trim();
  if (!server) {
    $('status').textContent = 'That is not a web address (http:// or https://).';
    return;
  }
  if (!looksLikeToken(token)) {
    $('status').textContent = 'A share token starts with pec_. Make one on the Echo page.';
    return;
  }
  // Ask for this one server only; the browser shows the prompt once.
  const granted = await chrome.permissions.request({ origins: [originPattern(server)] });
  if (!granted) {
    $('status').textContent = `Without access to ${server} the extension cannot send anything.`;
    return;
  }
  await chrome.storage.local.set({ server, token });
  $('server').value = server;
  $('status').textContent = 'Testing…';
  const result = await checkToken(fetch, server, token);
  $('status').textContent = result.ok
    ? `Connected as ${result.body?.email ?? 'you'}. Right-click anything to add it to Echo.`
    : result.error;
}

async function forget() {
  const { server } = await chrome.storage.local.get(['server']);
  await chrome.storage.local.remove(['token']);
  if (server && originPattern(server)) await chrome.permissions.remove({ origins: [originPattern(server)] });
  $('token').value = '';
  $('status').textContent = 'Forgotten. Revoke the token on the Echo page too.';
}

$('save').addEventListener('click', save);
$('forget').addEventListener('click', forget);
load();
