// The toolbar popup: add the current page, with an optional "why".
import { postShare, sharePayload } from './lib/echo.js';

const $ = (id) => document.getElementById(id);

async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const { server, token } = await chrome.storage.local.get(['server', 'token']);
  $('page').textContent = tab?.title || tab?.url || 'This tab';
  $('settings').addEventListener('click', (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });
  if (!server || !token) {
    $('share').disabled = true;
    $('status').textContent = 'Connect the extension to your Pratidhvani first (Settings).';
    return;
  }
  $('share').addEventListener('click', async () => {
    const built = sharePayload({ menuItemId: 'echo-page', pageUrl: tab?.url }, tab, $('why').value);
    if (!built.payload) {
      $('status').textContent = built.reason;
      return;
    }
    $('share').disabled = true;
    $('status').textContent = 'Adding…';
    const result = await postShare(fetch, server, token, built.payload);
    $('status').textContent = result.ok ? 'Added to Echo.' : result.error;
    $('share').disabled = result.ok;
  });
}

init();
