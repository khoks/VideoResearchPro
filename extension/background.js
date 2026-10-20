// "Add to Echo" service worker (S-3.7.3): context menus that send a page, a
// link, a quote or an image to the user's Echo inbox. Nothing is sent unless
// the user picks a menu item; the extension has no history permission.
import { MENUS, postShare, sharePayload } from './lib/echo.js';

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    for (const menu of MENUS) {
      chrome.contextMenus.create({ id: menu.id, title: menu.title, contexts: menu.contexts });
    }
  });
});

async function settings() {
  const { server, token } = await chrome.storage.local.get(['server', 'token']);
  return { server, token };
}

function flash(ok, message) {
  chrome.action.setBadgeBackgroundColor({ color: ok ? '#2f6f4e' : '#a33a2a' });
  chrome.action.setBadgeText({ text: ok ? '✓' : '!' });
  chrome.action.setTitle({ title: message });
  setTimeout(() => {
    chrome.action.setBadgeText({ text: '' });
    chrome.action.setTitle({ title: 'Add to Echo' });
  }, 5000);
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const { server, token } = await settings();
  if (!server || !token) {
    chrome.runtime.openOptionsPage();
    return;
  }
  const built = sharePayload(info, tab);
  if (!built.payload) {
    flash(false, built.reason);
    return;
  }
  const result = await postShare(fetch, server, token, built.payload);
  flash(result.ok, result.ok ? 'Added to Echo' : result.error);
});
