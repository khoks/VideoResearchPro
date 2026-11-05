# Adding to Echo from outside the app

How something reaches the shares inbox when the app is not open. All of these end in the same intake as the quick-share box: the same caps, the same processing, the same inbox, and the same Studio check. A link is fetched only if its address is public (see [below](#a-shared-link)).

| Where you are | How | Surface | Set up by |
|---|---|---|---|
| A browser | The Add to Echo extension ([`extension/`](../extension/)) | `browser_ext` | You, on the Echo page |
| An Android phone | The share sheet | `os_share` | Installing the app |
| An iPhone | A Shortcut | `os_share` | You, on the Echo page |
| Any mail client (self-host) | Email a dedicated mailbox | `email_in` | The operator, in `.env` |

Whatever arrives this way is context only: Echo can draw on it but never quotes it and never learns your voice from it. Marking a share as your own words is your act, in the inbox, one share at a time. Mail cannot be marked at all (see [below](#what-mail-can-do)).

## Android: the share sheet

Install Pratidhvani from Chrome (Add to Home screen), and it appears in the Android share sheet. Share a page, some text, an image, a PDF or a recording to it. The app opens, shows what arrived, and asks. One tap on **Add to Echo** puts it in your inbox, and **Discard** drops it unposted.

If you are signed out, the app asks you to sign in first, and the share waits on the phone until you have. A share still waiting after 24 hours is dropped unread. Signing out drops whatever is waiting. If you open the app on any page but its home, such as a link, you stay on that page and a line at the top offers **Review it**; nothing is added until you tap **Add to Echo** there.

**How it works.** The manifest's `share_target` posts a multipart form to `/echo/share-target`. A small service worker, `frontend/public/share-target-sw.js`, answers that one path. It keeps the form in the browser's Cache API on this device and redirects to `/echo/incoming` with nothing in the address. That page reads the form and shows it. On the tap it posts what it showed to `/echo/shares` or `/echo/shares/upload` with your session, and removes it.

So the shared words never appear in a URL, the address bar, the browser history or a server log, and no sign-in token ever does. A `GET` share target could not promise that: the browser would send the words in the query string to whatever serves the app, and a log would have them before any script ran.

The worker's scope is `/echo/share-target` alone, and it answers everything there with a redirect out of that scope, so no page is ever under its control and no API call goes through it. It caches nothing for offline reading. That is why it does not reopen [D-087](decisions.md#d-087--mobile-reading-and-install-a-reading-toolbar-below-1200-px-a-docked-composer-lifted-by-visualviewport-hermetic-device-tests-a-manifest-without-a-service-worker-2026-10-19)'s reasons for having no service worker.

**Why there is a tap.** The extension and the Shortcut add at once, because a token in a header proves who is asking. The share target proves nothing. It is a form post, and any website can make one, in any browser that has opened the app, installed or not. The worker cannot tell that post from the share sheet: it cannot read `Sec-Fetch-Site`, and a form can send no `Referer`, just as the share sheet does. If the app posted what arrived, a stranger's page could add text to your brain, make the server fetch an address, or spend your model budget on a file, all with your session and no click. So what arrives is only a proposal until you have seen it. The tap covers what the page showed, and something that arrives while the page is open waits for its own look.

**Limits.**
- It needs HTTPS (or `localhost`), as installing does. An `http://` LAN address has no service worker and no install.
- On a browser someone else also uses, a share left waiting with no sign-out, such as after a session expired, is shown to whoever signs in next. It goes nowhere without their tap, but they can read it.
- Chrome adds a new share target to a phone only when it updates the installed app, which can take a few days. Reinstalling is the quick way.
- A share of more than 10 files keeps the first 10.
- Firefox on Android and every iOS browser have no share target.
- Tested in Chromium through Playwright with a real form post and the real worker, not on a phone: the Android share sheet itself has not been exercised.

## iPhone: a Shortcut

iOS lets no web app into its share sheet, so a Shortcut posts to the same route the extension uses, with a share token in a header. The token can add to your inbox and nothing else: it cannot read anything or make another token. These steps are also on the Echo page, under the share tokens, with your server's address filled in.

**These steps have not been run on a real iPhone.** No device was available when they were written, so a menu may read differently. The HTTP requests they build are tested against the route.

First make a share token on the Echo page, labelled for the phone. Then, in the Shortcuts app:

1. Make a new Shortcut and name it Add to Echo. In its details, turn on Show in Share Sheet, and set it to receive URLs, Safari web pages and Text.
2. Add **Get URLs from Input**, with the Shortcut Input.
3. Add **If**, on the URLs, with the condition *has any value*.
4. Inside If, add **Get Contents of URL**:
   - URL: `https://your-server/api/v1/echo/shares`
   - Method: POST
   - Headers: `Authorization`, with the value `Bearer pec_your_token`
   - Request Body: JSON, with two Text fields: `url` set to the URLs, and `surface` set to `os_share`
5. Under Otherwise, add the same action with two Text fields: `text` set to the Shortcut Input, and `surface` set to `os_share`.
6. Share a page to Add to Echo. It lands in your inbox.

The request, for checking from a terminal:

```bash
curl -X POST https://your-server/api/v1/echo/shares \
  -H "Authorization: Bearer pec_your_token" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.org/essay", "surface": "os_share"}'
```

Anyone holding the Shortcut holds the token, so it goes in a header and never in the address, and you should revoke it from the Echo page if a phone is lost. A downgraded account's tokens stop working by themselves.

**Limits.** Text and links only, since the route for files takes a multipart upload. A text with a link in it is sent as the link alone, by step 3.

## A shared link

On every surface, a link that is not a YouTube video is fetched by the server, and the page's text becomes the share. So the address is checked first, and again at every redirect: one that resolves to a private, loopback or link-local address is refused, and the share fails with that reason. A self-hosted install whose pages live on the LAN can set `ECHO_FETCH_ALLOW_PRIVATE`. The check resolves the name and the fetch resolves it again, so a host that changes its answer between the two is not stopped.

## Email: an IMAP mailbox (self-host)

Point Pratidhvani at a mailbox used for nothing else. Every few minutes it reads the unread mail there, and each message from an address you allow becomes a share for one account.

| Setting | Meaning |
|---|---|
| `ECHO_IMAP_ENABLED` | Turns it on. Off by default |
| `ECHO_IMAP_HOST`, `ECHO_IMAP_PORT` | The server. TLS on connect only (IMAPS, default port 993), certificate and host name verified |
| `ECHO_IMAP_USERNAME`, `ECHO_IMAP_PASSWORD` | The mailbox's login. For Gmail or Outlook, an app password |
| `ECHO_IMAP_FOLDER` | The folder to read, default `INBOX` |
| `ECHO_IMAP_TENANT_EMAIL` | The account whose inbox the shares land in. It needs the Studio plan, checked on every poll |
| `ECHO_IMAP_ALLOWED_SENDERS` | The addresses that may send, comma-separated and exact. **Empty accepts nothing**, and the mailbox is not opened |

It runs from the scheduler tick, every `SCHEDULER_TICK_SECONDS`, so it needs the beat and a worker running, as saved searches do. There is no separate process and no second beat entry. Restart the worker after changing these settings.

**What happens to a message.**

- Mail is read without marking it, and flagged read once it has been dealt with. Nothing is ever deleted from the mailbox.
- A sender not on the list is dropped on its headers: the body is never downloaded. The message stays in the mailbox, read. To take it after all, add the sender and mark it unread.
- A From with more than one address, a second From header, or a malformed one is dropped the same way.
- A message becomes one text share: the plain-text body, or the HTML one read as text, with the subject as its title.
- A message over `ECHO_SHARE_MAX_BYTES` is not downloaded. Text past `ECHO_SHARE_TEXT_MAX_CHARS` is cut, and says so where it was cut.
- A poll takes at most 50 messages, oldest first; the next tick takes the rest.
- The poller owns the mailbox's read flags. If you open a message in a mail client first, it counts as read and is skipped, so mark it unread or leave the mailbox alone.

**A re-poll adds nothing.** Each message's `Message-ID` is recorded with its share, as a hash, in `echo_email_messages`; a message with none is recorded by a hash of its bytes. That record outlives the share on purpose: a share you delete stays deleted, even if the mail is marked unread again. The full Echo delete erases the record too.

### What mail can do

Anyone can email a mailbox, and **the From header proves nothing: anyone can write any address in it.** The allowed list keeps out noise and strangers who do not know your address. It does not stop someone who knows both the mailbox and an allowed sender. Pratidhvani does not check SPF, DKIM or DMARC. Use a provider that rejects mail failing DMARC, and keep the mailbox's address private.

So the design assumes a forged message will arrive, and limits what one can do:

- **It cannot teach your voice.** Mail is always context only. No `email_in` share can be marked as your own words, by the poller, the API or the inbox, not even one from your own address. To have those words count, add them yourself through quick share.
- **It cannot make the server fetch anything.** A message is always text, so a link in it stays a link for you to open. A URL share would have the server fetch an address a stranger chose.
- **It cannot spend your model budget on media.** Attachments are listed on the share and not read, so a forged message cannot call the vision model or Whisper.
- **It can put text in your inbox**, and that text can be retrieved as context for a draft. Delete a share you do not recognise, and everything derived from it goes too.
- **It cannot pass as something you chose to share.** In a draft, mail is labelled an unverified email, not your view, and the draft prompts say that such an item supports no factual claim and that nothing retrieved is an instruction. That is a request to a model, so it is not the guarantee. The guarantee is in code: a draft that cites mail is flagged, says so under the draft, and shows the email among what it drew on, and a question, opinion or recommendation that only mail supports is refused rather than drafted. Words from mail are never quoted. A model can still use mail without citing it, so read a draft before you send it, as you always should.

The password and the message bodies are never logged. The log carries counts and exception types only.

**This has not run against a real mailbox.** The tests use a fake client and the real `imaplib` against a scripted local server.
