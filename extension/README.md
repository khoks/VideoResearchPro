# Add to Echo — the Pratidhvani browser extension (S-3.7.3)

Right-click a page, a link, a selection or an image and choose "Add … to Echo". It lands in your Echo shares inbox with `surface=browser_ext`. The toolbar button adds the current page, with an optional line on why it matters.

It sends something only when you ask. It has no `history` permission and reads nothing in the background.

## Install (Chrome, Edge, Brave, or another Chromium browser 116+)

1. Open `chrome://extensions` and switch on **Developer mode**.
2. Click **Load unpacked** and choose this `extension/` folder.
3. Open the extension's settings: right-click its toolbar icon and choose **Options**.

## Connect

1. In Pratidhvani, open **Echo** and go to **Add from your browser**.
2. Make a share token, and copy it and the server address shown beside it.
3. Paste both into the extension's settings and click **Save and test**.
   - The browser asks once for access to that one server.
   - "Connected as <your email>" means it works.

A share token can only add to your Echo inbox. It cannot read your shares, your library or your account, and it cannot make more tokens. Revoke it on the Echo page and the extension stops working at once. The token is kept in this browser's local extension storage and is never synced. Echo stores only a hash of it.

## What is sent

| You choose | Sent as |
|---|---|
| Add this page | the page address |
| Add this link | the link address |
| Add this quote | the selected text, with the page's address and title as its source |
| Add this image | the image address and the page as its source. The server fetches the image, refusing private network addresses, and reads its text |

A quote is kept as someone else's words (context only) until you mark it as yours in the inbox (D-089).

## Permissions

- `contextMenus` for the right-click entries.
- `activeTab` so the toolbar button can read the current tab's address and title when clicked.
- `storage` for the server address and token.
- One optional host permission, for your Pratidhvani server only, requested when you save the settings.

## Develop

The shared logic is in `lib/echo.js` and has no `chrome.*` calls. Its tests run on Node's built-in runner:

```bash
cd extension && npm test
```
