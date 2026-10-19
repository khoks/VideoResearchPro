# Echo (L3) connector research — pull-mode activity connectors and push-mode "constant-stream" intake

**Date of research:** 2026-10-19
**Method:** WebSearch (standard + extended) and direct fetch of vendor documentation. The per-turn WebSearch budget (200 calls) ran out near the end; every claim that could not be verified against a primary source is marked **[unverified]** or **[secondary source only]**. Nothing in this file was written from memory alone when a source was reachable; where a page 404'd or redirected into a loop, that is stated.

---

## Summary

1. **YouTube watch history is not available through the Data API v3.** The `watchHistory`/`watchLater` playlist properties were neutered in Sept 2016 (return `HL`/`WL` placeholders) and removed from the docs in Sept 2020; the `watchHistoryNotAccessible` error text says history "cannot be retrieved using the API". The only programmatic path is Google's **Data Portability API** scope `dataportability.myactivity.youtube`, which is a **restricted** scope (annual CASA assessment). Practical answer: **Takeout file import** (`history/watch-history.json`).
2. **Spotify is now effectively single-user for self-host and non-viable for SaaS.** Since Feb 11 / Mar 9 2026, Development Mode apps need a Premium-subscribed owner, are capped at **5 allow-listed users**, and Extended Quota requires a registered business with **250k MAU**. Recently-played is a ~50-item window; the lifetime "Extended streaming history" export is the real bootstrap.
3. **Gmail read-only is a restricted scope** (`gmail.readonly` is in Google's restricted list) → annual CASA Tier 2 assessment (TAC Security list price ~$540/yr; other labs quote $8k–$40k). Self-host alternative: IMAP with a Google **App Password** (needs 2-Step Verification) or a BYO Google Cloud project in Testing mode. Calendar read-only is **sensitive, not restricted** (3–5 business-day verification, no assessment).
4. **Strava's API is a dead end for an LLM product.** Policy effective 1 June 2026 (§5.3) prohibits using API data "in connection with the development, training, evaluation, or operation of any AI Application", explicitly including "ingestion into a context window or working memory"; Standard tier now also requires a paid Strava subscription. Use the bulk export only. **Goodreads** API died Dec 2020 (CSV export only); **Letterboxd** API beta explicitly refuses "LLM or GPT-related use" and "private or personal projects" (CSV export only). **Apple Health** has no web API (export.zip/export.xml only).
5. **GitHub is the cheapest pull connector**: `GET /users/{username}/events` with fine-grained "Events: read", 5,000 req/h, but only the last **300 events / 30 days** and 30 s–6 h latency.
6. **Browser history via extension is feasible but policy-heavy**: `history` permission triggers the warning "Read and change your browsing history on all signed-in devices"; Chrome Web Store requires a posted privacy policy, in-product disclosure + consent, HTTPS transport, Limited Use; a tightened Limited Use rule is enforced from **1 Aug 2026**. Firefox supports `browser.history` on desktop (49+) but **not** Firefox for Android; Safari: no.
7. **Push intake**: Web Share Target works on installed PWAs in Chrome Android 76+ and desktop Chrome 89+; **iOS Safari still cannot register a PWA as a share target** (no Apple statement found changing this) → use an iOS Shortcut that POSTs to the app. Inbound email: Mailgun Free (100/day, 1 route) and Cloudflare Email Routing (Free plan; Worker handler under Workers Free 100k req/day) are $0 entry points; Postmark needs Pro ($16.50/mo); self-host = `imaplib` (PSF-2.0) / IMAPClient (BSD-3-Clause, has IDLE).
8. **Export formats are parseable but locale-fragile**: WhatsApp iOS `[dd.mm.yy, hh:mm:ss] Name: text` + `<attached: …>`, Android `dd.mm.yy, hh:mm - Name: text` + `(file attached)` / `<Media omitted>`; Google Keep = one JSON per note (`textContent`, `listContent[].{text,isChecked}`, `labels[].name`, `isArchived`, `userEditedTimestampUsec`); TikTok JSON `Activity → "Like List" → ItemFavoriteList[{Date, Link}]`; Instagram `liked_posts.json` structure is community-reported only.
9. **OCR**: Tesseract/pytesseract, EasyOCR, PaddleOCR and RapidOCR are all **Apache-2.0** and all have Devanagari models (PaddleOCR PP-OCRv5 multilingual added Devanagari on 2025-10-16). A vision-LLM pass costs roughly **$0.0001 (Gemini 2.5 Flash-Lite) to $0.005 (Claude Opus 5.5) per 1-megapixel meme** — cheap enough to use as the fallback for stylised text.
10. **Zero-knowledge mode is incompatible with server-side embeddings.** sentence-transformers/Chroma need plaintext; the only honest options are (a) client-side embeddings (Transformers.js runs `feature-extraction` in-browser via WASM/WebGPU) with the vectors themselves treated as sensitive, (b) at-rest encryption with a trusted server, or (c) local-only. GDPR Art 20/17 and India DPDP (Rules notified 13 Nov 2025; substantive duties ~May 2027; **no portability right** in DPDP) both apply to a hosted store; no comparable product (Limitless, Mem, Reflect, Obsidian) has a documented answer to "other people's content" beyond pushing the consent burden onto the user.

---

## 1. YouTube watch history, liked videos, subscriptions, Takeout, scopes

### Is watch history available via Data API v3? — **No.**
- Revision history (official): **Aug 11 / Sep 15 2016** — `contentDetails.relatedPlaylists.watchHistory` and `.watchLater` "now contain values of `HL` and `WL`, respectively, for all channels" (i.e. placeholders). **Nov 2 2016** — new `watchHistoryNotAccessible` error: "tried to retrieve "watch history" playlist items, but those cannot be retrieved using the API." **Sep 9 2020** — the two properties, "announced as deprecated in 2016", removed from the documentation. **Jan 28 2021** — the error entries themselves removed, with the note that "users' watch history and watch later lists are, indeed, not accessible via the API". https://developers.google.com/youtube/v3/revision_history
- Today the `channels` resource lists only `contentDetails.relatedPlaylists.likes`, `.favorites` (deprecated) and `.uploads`. https://developers.google.com/youtube/v3/docs/channels
- Community confirmation (blog): "The Data API v3 … used to expose contentDetails.relatedPlaylists.watchHistory … It's returned an empty placeholder since around 2016." https://bhanueso.dev/blips/youtube-watch-history-extension

### What IS available with `youtube.readonly`
| Need | Call | Notes | Source |
|---|---|---|---|
| Liked videos | `videos.list?myRating=like` | `maxResults` ≤ 50, cost 1 unit, **results capped at 1,000 videos** even if `totalResults` is higher | https://developers.google.com/youtube/v3/docs/videos/list |
| Subscriptions | `subscriptions.list?mine=true` | `maxResults` 0–50, cost 1 unit | https://developers.google.com/youtube/v3/docs/subscriptions/list |
| Playlists / Liked (`LL`) | `playlists.list?mine=true`, `playlistItems.list?playlistId=LL` | standard | https://developers.google.com/youtube/v3/guides/implementation/playlists |
| Quota | default **10,000 units/day** for list endpoints (plus 100 `search.list` and 100 `videos.insert` per day); 1 unit per list call; extension via form + compliance audit | https://developers.google.com/youtube/v3/getting-started |

Scopes listed by Google: `youtube`, `youtube.readonly`, `youtube.force-ssl`, `youtube.upload`, `youtube.channel-memberships.creator`, `youtubepartner`, `youtubepartner-channel-audit`. https://developers.google.com/youtube/data/guides/auth/installed-apps

### Google Data Portability API — the only programmatic watch-history path
- Scope `https://www.googleapis.com/auth/dataportability.myactivity.youtube` ("Move a copy of your YouTube activity") is **Restricted**; also restricted: `myactivity.{maps,play,search,shopping}`, `chrome.history`, `chrome.autofill`, `chrome.bookmarks`, `youtube.channel`, `youtube.private_videos`. Sensitive (not restricted): `youtube.subscriptions`, `youtube.{public,private,unlisted}_playlists`, `youtube.comments`, `youtube.music`, etc. https://developers.google.com/data-portability/user-guide/scopes
- Flow: `portabilityArchive.initiate` with `resources=["myactivity.youtube"]` → poll archive state → signed download URL; one-time or **time-based access** (export every 24 h until consent expires); **time filters** supported for the YouTube activity scope (incremental exports). Must start the archive within 24 h of consent; under-18 accounts unsupported; billing must be enabled on the GCP project; **annual re-verification**; "Verify the Data Portability API is available in your location" (region list is on a support page I could not fetch — 404). https://developers.google.com/data-portability/user-guide/overview , https://developers.google.com/data-portability/user-guide/time-based , https://developers.google.com/data-portability/user-guide/time-filter
- Google's Restricted Scopes page lists the Data Portability API as a restricted family (16 scopes, incl. `dataportability.myactivity.youtube`). https://support.google.com/cloud/answer/13464325
- The `youtube.*` resource groups export **CSV** (subscriptions: `Channel ID, Channel URL, Channel Title`; playlists; comments; music library `Song Title, Album Title, Artist Name`…) — watch history itself lives under the **My Activity** schema, not the YouTube schema. https://developers.google.com/data-portability/schema-reference/youtube

### Google Takeout export format (manual, no verification)
- Official My Activity schema (fields vary per record): `header` (string, e.g. "YouTube"), `title` ("Watched …", "Subscribed to …"), `titleUrl` (watch URL), `subtitles` (channel name + url), `time` (ISO-8601 UTC, e.g. `2023-08-23T03:49:28.734Z`), `products` (list), `activityControls` (e.g. "YouTube watch history", "YouTube search history"), `details` (e.g. "From Google Ads"), plus `locationInfos`, `imageFile`, `audioFiles`, `attachedFiles`. https://developers.google.com/data-portability/schema-reference/my_activity
- Takeout layout: `Takeout/YouTube and YouTube Music/history/watch-history.json|.html`, `history/search-history.json`, `subscriptions/subscriptions.csv` (sometimes missing; OPML option), `playlists/`, `comments/`, `live chat messages/`, `uploads/videos.json`, `captions/`. JSON or HTML selectable at export time. **[secondary source]** https://takeoutday.org/guides/how-to-export-youtube-data ; community parsers: https://github.com/positron48/youtube-history-analyzer , https://github.com/PierreBeur/youtube-history-viewer
- Known gotcha: `subtitles` is an array; ad impressions appear as records with `details: "From Google Ads"`; titles are prefixed "Watched ".

### OAuth verification for `youtube.readonly`
- YouTube scopes are **sensitive** (Google's sensitive-scope page uses "deleting a YouTube video" as its example; Calendar "reading events" is its other example). Sensitive-scope verification requires: privacy policy on the same domain as the home page and linked from the consent screen; publicly accessible home page; **unlisted YouTube demo video** showing the consent flow with the client ID visible in the address bar; per-scope justification. "Typically takes 3–5 business days." https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification
- **CASA is NOT required for `youtube.readonly`** — the security assessment applies only to restricted scopes (Gmail, Drive, Fit, Chat, Data Portability, Photos Ambient, Health). https://support.google.com/cloud/answer/13464325
- Unverified apps requesting sensitive/restricted scopes: "Danger" warning screen and a **hard, lifetime cap of 100 users** that "cannot be reset or changed"; Testing-mode projects are separately limited to 100 listed test users. https://support.google.com/cloud/answer/15549945 , https://developers.google.com/identity/protocols/oauth2/production-readiness/overview
- Third-party guides claim a **7-day refresh-token expiry** for External apps in Testing status — stated by Nylas/Unipile, **not confirmed** on Google's own pages I fetched. https://developer.nylas.com/docs/cookbook/use-cases/build/fix-google-access-denied/ , https://www.unipile.com/google-oauth-100-user-limit/
- Google rejects over-scoped requests (one project had a review turned down for requesting scopes its code did not call). https://github.com/xerk/tadween/pull/80

---

## 2. Spotify Web API and data export

### Endpoints relevant to Echo
| Endpoint | Scope | Limits | Source |
|---|---|---|---|
| `GET /me/player/recently-played` | `user-read-recently-played` | `limit` 1–50; `before`/`after` ms cursors (mutually exclusive); "Currently doesn't support podcast episodes" | https://developer.spotify.com/documentation/web-api/reference/get-recently-played |
| `GET /me/tracks` (saved tracks) | `user-library-read` | `limit` ≤ 50, not deprecated (some fields like `popularity`, `preview_url` are) | https://developer.spotify.com/documentation/web-api/reference/get-users-saved-tracks |
| Saved shows/episodes/albums | `user-library-read` | GET endpoints survive; **save/remove/contains** were consolidated into `PUT/DELETE /me/library` and `GET /me/library/contains` in Feb 2026 | migration guide below |
| Top items | `user-top-read` | — | https://developer.spotify.com/documentation/web-api/concepts/scopes |

- **Recently-played depth is ~50 items.** Spotify's reference does not state a history depth; community moderators and third-party docs consistently report that cursors "paginate within that limit but not outside of it", and `before` cursors past the window return empty. **[secondary sources]** https://community.spotify.com/t5/Spotify-for-Developers/Get-all-recently-played-tracks-for-a-given-period/td-p/5860931 , https://community.spotify.com/t5/Spotify-for-Developers/before-and-after-are-utterly-useless-with-me-player-recently/td-p/5520713
- **Rate limits:** rolling 30-second window, HTTP 429 with `Retry-After`; no numbers published; Development Mode additionally has a *quota* (429 body `"reason": "QUOTA_EXCEEDED"`). https://developer.spotify.com/documentation/web-api/concepts/rate-limits

### November 2024 restrictions
Removed for new apps and dev-mode apps without a pending extension (apps already in extended mode unaffected): Related Artists, Recommendations, Audio Features, Audio Analysis, Featured/Category Playlists, genre seeds, algorithmic/editorial playlists, 30-second previews; now 403. Reporting attributes it to AI-training concerns (Spotify's own rationale not confirmed). https://spotify.leemartin.com/ , https://community.spotify.com/t5/Spotify-for-Developers/Why-did-Spotify-deprecate-basically-half-of-the-webAPI-endpoints/td-p/6547151 , https://freqblog.com/blog/spotify-audio-features-replacement-2026/

### 2025–2026 Development-Mode changes (official)
- **Extended Quota Mode eligibility (since 15 May 2025):** organisations only — "Established Business Entity", "Operating an active, and Launched Service", "at least 250k MAUs", "available in key Spotify markets", "Commercial Viability"; review "can take up to six weeks". https://developer.spotify.com/documentation/web-api/concepts/quota-modes
- **February 2026 migration:** new apps from **11 Feb 2026**, existing apps migrated **9 Mar 2026**. "All Development Mode apps require the app owner to have an active Spotify Premium subscription" (app stops working if it lapses); **5 users per app** (down from 25), 1 Client ID (grandfathered apps keep theirs); search `limit` max 50→10, default 20→5; batch `GET /tracks|/albums|/artists|/episodes|/shows` removed; browse, artist top-tracks, other-user profiles/playlists, `/markets` removed; many response fields removed (`popularity`, `available_markets`, user `email`/`country`/`product`). https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide ; news: https://techcrunch.com/2026/02/06/spotify-changes-developer-mode-api-to-require-premium-accounts-limits-test-users/
- **23 Jul 2026:** up to 25 Client IDs per developer account, but quota is now **per developer account** (shared across all dev-mode apps). https://developer.spotify.com/blog/2026-07-23-web-api-quota-updates
- **[unverified]** a six-month lifetime on user authorisations for new apps from 18 Jun 2026 (one secondary guide). https://vorplabs.com/agent-tools/spotify-api-changes

### "Download your data" export (bootstrap)
Three packages: Account data (incl. 1-year `StreamingHistory`: stream end time UTC, creator, item name, `msPlayed`), **Extended streaming history** (lifetime; 21 fields: end time, username, platform, ms played, country code, IP address, user agent, track/artist/album name, track URI, episode/show name, episode URI, reason start/end, shuffle, skipped, offline, offline timestamp, private session, incognito), Technical log. Delivery times not stated on the page. https://support.spotify.com/us/article/understanding-my-data/
JSON key names seen in real exports (community): `ts`, `ms_played`, `conn_country`, `master_metadata_track_name`, `master_metadata_album_artist_name`, `spotify_track_uri`, `reason_start`, `reason_end`; metadata fields can be null for some records; a "Read Me First – Extended Streaming History" file ships with the archive. **[secondary]** https://github.com/Wallerand/spotify-unwrapped , https://community.spotify.com/t5/Other-Podcasts-Partners-etc/Extended-Streaming-History-missing-track-metadata/td-p/6269152

---

## 3. Gmail (read-only), CASA, user cap, IMAP; Google Calendar scope class

### Gmail scope classification (official table)
- **Restricted:** `https://mail.google.com/`, `gmail.readonly`, `gmail.compose`, `gmail.insert`, `gmail.modify`, `gmail.metadata`, `gmail.settings.basic`, `gmail.settings.sharing`.
- **Sensitive:** `gmail.send`, `gmail.addons.current.message.metadata`, `gmail.addons.current.message.readonly`.
- **Non-sensitive:** `gmail.labels`, two add-on scopes. https://developers.google.com/workspace/gmail/api/auth/scopes
- `https://mail.google.com/` "covers any usage of IMAP, SMTP, and POP3 protocols" — i.e. OAuth-based IMAP is also restricted. https://support.google.com/cloud/answer/13464325

### Restricted-scope verification / CASA
- Applies when the app accesses restricted-scope data "from or through a third-party server"; "If you store or transmit restricted scope data on servers, then you need to complete a security assessment." Assessment by Google-empanelled assessors under the App Defense Alliance / **CASA** framework; **reassessment at least every 12 months** after the Letter of Assessment; review "can potentially take several weeks". https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
- Cost (no official price list): TAC Security Tier 2 widely cited at **$540–$1,800/yr** (Google-negotiated rate); other labs quoted $8k–$40k; the "$50k" figure is outdated/top-tier. https://deepstrike.io/blog/google-casa-security-assessment-2025 , https://bright-softwares.com/blog/en/google-workspace/the-50000-gmail-add-on-myth-what-google-s-casa-certification-really-costs , https://community.latenode.com/t/is-casa-tier-2-assessment-necessary-for-all-gmail-api-apps-options-for-indie-developers/22861
- **User cap:** unverified apps with sensitive/restricted scopes — lifetime cap of 100 users; Testing-mode projects limited to 100 test users. https://support.google.com/cloud/answer/15549945
- Self-host escape hatch: each operator creates their **own GCP project** and adds themselves as a test user (Testing mode) — restricted scopes work for test users without verification; the 7-day refresh-token expiry claim for External/Testing apps is **[unverified]** against Google docs.

### IMAP alternative
- Google removed "Less secure apps"/basic auth: new connections blocked from summer 2024, **all accounts cut off 14 Mar 2025** (IMAP, SMTP, POP, CalDAV, CardDAV) "with the exception of app passwords". https://support.google.com/a/answer/9003945
- **App Passwords**: 16-digit codes; "can only be used with accounts that have 2-Step Verification turned on"; unavailable under Advanced Protection, security-key-only 2SV, and possibly Workspace accounts. https://support.google.com/accounts/answer/185833
- OAuth IMAP (XOAUTH2) needs `https://mail.google.com/` → restricted. So for self-host, **App Password + imaplib/IMAPClient** is the path; for SaaS, Gmail read-only means CASA.

### Google Calendar
- `calendar.readonly` is **sensitive** (Google's sensitive-scope page cites "reading events stored in Google Calendar" as its example); Calendar is **not** in the restricted families list. Verification 3–5 business days; no CASA. https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification , https://support.google.com/cloud/answer/13464325 , scopes: https://developers.google.com/calendar/api/auth

---

## 4. Apple Health, Strava, Goodreads, Letterboxd

### Apple Health
- **No web API**; HealthKit is on-device only. Export via Health app → profile → "Export All Health Data" → `export.zip` containing `export.xml` (+ `export_cda.xml`, workout routes GPX, ECG CSVs per community tools). **[Apple support page fetched did not include the export section; contents list is community-reported]**
- `export.xml` = `<Record type="HKQuantityTypeIdentifierHeartRate" sourceName= unit= startDate= endDate= value=…>`; category records (sleep) have no `unit`; size commonly **1–2 GB+** for multi-year Apple Watch users → stream-parse (`iterparse`), never load whole. https://developer.apple.com/forums/thread/20345 , https://pypi.org/project/apple-health-extractor/0.1.3 , https://www.fitmesh.fit/it/blog/how-to-export-apple-health-data

### Strava
- **Nov 11 2024 agreement:** "Third-party apps may now only display a user's Strava activity data to that specific user"; "explicitly prohibit third parties from using any data obtained via Strava's API in artificial intelligence models"; "<0.1% of applications" affected. https://press.strava.com/articles/updates-to-stravas-api-agreement ; critique: https://www.dcrainmaker.com/2024/11/stravas-changes-to-kill-off-apps.html
- **API Policy effective 1 June 2026** (official): §5.3 "You may not use the Strava API Materials or Strava Data, directly or indirectly, in connection with the development, training, evaluation, or operation of any AI Application" — prohibited list includes "ingestion into a context window or working memory"; §2.3 data displayed "only to that user"; §3.3(a) Standard tier requires "an active Strava subscription" ($11.99/mo or $79.99/yr US per secondary reporting; existing devs had until 30 Jun 2026); §3.3(b) Extended Access at "10,000 users or more"; club endpoints removed 1 Sep 2026; new base URL 4 Jan 2027, header-only tokens from 1 Jun 2027. https://www.strava.com/legal/api_policy , https://appsforstrava.com/blog/strava-developer-program-changes-2026 , https://techcrunch.com/2026/06/01/strava-declares-war-on-scrapers-ahead-of-ipo/
- Rate limits: 200 req/15 min and 2,000/day overall; 100/15 min and 1,000/day non-upload; 429 on breach; resets at :00/:15/:30/:45 and midnight UTC; upgraded tier 400/4,000. https://developers.strava.com/docs/rate-limits/
- **Bulk export** (Settings → My Account → "Download your account"): archive emailed as ZIP; contains `activities.csv` plus original per-activity files (FIT/GPX/TCX) per secondary guides; official help only documents single-activity "Export Original" (often FIT) and `/export_tcx`. https://support.strava.com/hc/en-us/articles/216918437-Exporting-your-Data-and-Bulk-Export , https://takeoutday.org/guides/how-to-export-strava-data
- **Conclusion:** an Echo that feeds Strava data to an LLM via the API breaches §5.3; import the bulk export instead (user-owned data, outside the API agreement).

### Goodreads
- Public API retired from **8 Dec 2020** (no new keys; unused keys disabled; by mid-2022 remaining keys stripped of many fields). https://waxy.org/2020/12/amazon-owned-goodreads-quietly-shutters-api/ , https://blog.openlibrary.org/2020/12/13/importing-your-goodreads-accessing-them-with-open-librarys-apis/ , https://brandur.org/atoms/gq7cdyc
- Export = CSV from My Books → Import and export ("Export Library"). Goodreads help article URL returned 404 on fetch; columns (`Book Id, Title, Author, ISBN, ISBN13, My Rating, Average Rating, Publisher, Number of Pages, Year Published, Date Read, Date Added, Bookshelves, Exclusive Shelf, My Review, Private Notes, Read Count…`) are **[not verified this session — confirm against a real export]**. RSS shelf feeds are capped at ~100 books. https://glama.ai/mcp/servers/w2kfmsb5g1

### Letterboxd
- API is private/invitation-only (email api@letterboxd.com). The beta page states it is **not granting access** for "data-analysis, visualization or recommendation projects", "LLM or GPT-related use", "private or personal projects", or anything replicating paid features. https://letterboxd.com/api-beta/ , https://support.letterboxd.com/hc/en-us/articles/15269070369551-Do-you-have-mobile-apps-or-an-API
- Export: Settings → Import & Export → "Export your data" (`letterboxd.com/settings/data/`) → ZIP of CSVs (diary, ratings, watchlist, lists, reviews, watched). Official page documents only the **import** CSV (`LetterboxdURI, tmdbID, imdbID, Title, Year, Directors, Rating, Rating10, WatchedDate, Rewatch, Tags, Review`; UTF-8, comma-delimited) — export columns mirror it **[secondary]**. https://letterboxd.com/about/importing/ , https://docs.movary.org/features/letterboxd/ , https://git.aaronmanning.net/aaronmanning/letterboxd-export

---

## 5. GitHub API for the user's own activity

- `GET /users/{username}/events` — "If you are authenticated as the given user, you will see your private events"; fine-grained PAT permission **"Events" (read)**; `per_page` ≤ 100; "The timeline will include up to **300 events**. Only events created within the past **30 days**"; "event latency can be anywhere from 30s to 6h"; "not built to serve real-time use cases". https://docs.github.com/en/rest/activity/events?apiVersion=2022-11-28
- Rate limits: unauthenticated 60/h per IP; authenticated user 5,000/h (15,000 for Enterprise Cloud GitHub Apps); secondary limits 100 concurrent, 900 points/min REST (GET = 1 pt). https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2022-11-28
- The app's existing GitHub OAuth login can be reused; add `read:user` + a fine-grained "Events: read" (or classic `repo` for private repo commit listing via `GET /repos/{o}/{r}/commits?author=`). Commits older than 30 days require walking repos directly (not the events feed).

---

## 6. Browser history (Chrome/Firefox extension)

- Chrome `chrome.history`: declare `"history"` in `permissions`; `search({text, startTime, endTime, maxResults})` — `maxResults` default 100, default window last 24 h; `getVisits`, `onVisited`, `onVisitRemoved`; promise-based since Chrome 96; MV3 only. https://developer.chrome.com/docs/extensions/reference/api/history
- Install warning for `history`: **"Read and change your browsing history on all signed-in devices."** (`tabs` alone: "Read your browsing history."; `contextMenus`/`activeTab`: no warning.) https://developer.chrome.com/docs/extensions/reference/permissions-list
- MV3: `host_permissions` separate from `permissions`; service worker is event-driven and must use `chrome.storage`; list your API origin in `host_permissions` for cross-origin `fetch`. https://extension.js.org/docs/concepts/manifest-v3
- **Chrome Web Store policy:** any product handling user data must post a privacy policy; browsing history ("domains and URLs the browser interacts with") is explicitly user data, collectable only "to the extent required for a user-facing feature" prominently described; **in-product disclosure + affirmative consent before collection** (a privacy-policy link alone is insufficient); HTTPS/WSS transport; strong encryption at rest; Limited Use (no ads, no human reading). https://developer.chrome.com/docs/webstore/program-policies/user-data-faq , https://developer.chrome.com/docs/webstore/program-policies/limited-use
- **2026 update (enforced 1 Aug 2026):** "Any user data collected by an extension must now be strictly necessary to the extension's disclosed single purpose"; all collection "prominently disclosed"; developers "must proactively disclose to users if their data handling practices change". https://developer.chrome.com/blog/cws-policy-updates-2026
- **Firefox:** `browser.history` with `"history"` permission; MV3 GA since Firefox 109; MV3 host permissions are opt-in at install (prompt since Firefox 127). Browser-compat-data: Chrome 5+, **Firefox 49+ desktop, Firefox for Android: not supported, Safari: not supported**. https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/history , https://raw.githubusercontent.com/mdn/browser-compat-data/main/webextensions/api/history.json , https://blog.mozilla.org/addons/2022/11/17/unified-extensions-button-and-how-to-handle-permissions-in-manifest-v3/

---

## 7. Push intake surfaces

### Web Share Target (PWA)
- Manifest `share_target` {`action`, `method` GET|POST, `enctype`, `params` {`title`,`text`,`url`,`files[{name,accept}]`}}; files require POST + `multipart/form-data`. https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest/Reference/share_target
- Support: **Chrome 76+ on Android, Chrome 89+ on desktop**; "On all platforms, your web app has to be installed before it will show up as a potential target". https://developer.chrome.com/docs/capabilities/web-apis/web-share-target
- **iOS/iPadOS: not supported** — a PWA cannot register as a share-sheet recipient (outbound `navigator.share()` works since iOS 14). No Apple statement found reversing this as of Oct 2026. **[vendor blogs + HN, no Apple source]** https://tappwa.com/blog/ios-pwa-limitations-2026 , https://www.magicbell.com/blog/pwa-ios-limitations-safari-support-complete-guide , https://news.ycombinator.com/item?id=38913038 , https://caniuse.com/web-share
- **iOS workaround = Shortcuts**: an Action-Extension Shortcut accepting URLs/text/images from the share sheet that calls "Get Contents of URL" (POST, with a bearer token) to the Echo intake endpoint; PageCrawl and ErikrafT Drop ship exactly this. https://www.pagecrawl.io/help/tutorials/article/add-page-from-ios-safari , https://deepwiki.com/erikraft/Drop/5.9-ios-shortcuts , https://support.apple.com/en-kg/guide/shortcuts/apd7644168e1/2.1/ios

### Browser-extension capture (MV3)
`contextMenus` (no install warning) + `activeTab` + service-worker `fetch` to the Echo API (origin in `host_permissions`) covers "save selection / page / image" without the `history` permission at all. Policy obligations from §6 still apply (privacy policy, disclosure, HTTPS).

### Inbound email — SaaS
| Provider | Entry price | Inbound | Source |
|---|---|---|---|
| **Postmark** | Free 100/mo (no inbound); Basic $15; **Pro $16.50/mo** (10k, +$1.30/1k) — "Inbound email processing" listed on Pro and Platform only | counts toward volume (implied, not stated) | https://postmarkapp.com/pricing |
| **Mailgun** | **Free: 100/day, 1 inbound route**; Basic $15 (10k, 5 routes); Foundation $35 (50k, "Full access to inbound routing") | bundled | https://www.mailgun.com/pricing/ |
| **SendGrid** | pricing page redirect-looped on fetch; secondary: Essentials $19.95/mo 50k, Inbound Parse included on paid plans, 60-day trial 100/day **[unverified]** | included | https://mails.ai/blog/best-inbound-email-parsing-api-for-developers |
| **Cloudflare Email Routing + Email Workers** | Routing "Available on Free and Paid plans"; 200 rules/200 addresses; 25 MiB max message; Worker handler runs under **Workers Free: 100k req/day, 10 ms CPU** (complex handlers may hit `EXCEEDED_CPU` → Workers Paid **$5/mo**, 10M req, 30M CPU-ms) | free | https://developers.cloudflare.com/email-routing/ , https://developers.cloudflare.com/email-routing/limits , https://developers.cloudflare.com/workers/platform/pricing/ |

### Inbound email — self-host
- `imaplib` (Python stdlib, **PSF-2.0**); **IMAPClient** (**BSD-3-Clause**, "New BSD"), wraps imaplib, supports `idle()` / `idle_check(timeout)` / `idle_done()`; docs advise renewing IDLE every 10 min; does not handle low-level socket errors itself. https://imapclient.readthedocs.io/ , https://imapclient.readthedocs.io/en/3.0.1/advanced.html
- Celery beat polling every N minutes is simpler than IDLE in a worker process; IDLE needs a dedicated long-lived connection.

---

## 8. Export formats users will share

### WhatsApp chat export (.txt or .zip with media)
- **iOS**: `[29.01.18, 23:33:00] Alice: Hello?` — bracketed timestamp with seconds, locale date separators (`.` or `/`), optional AM/PM; media as `<attached: 00000012-PHOTO-2018-01-29-23-33-00.jpg>` (WhatsR regex `^<attached:\s(.)*?\.(.)*?>$`); "without media" variant uses `<media omitted>`; system messages for locations (`maps.google.com/?q=`), `live location shared`. https://search.r-project.org/CRAN/refmans/WhatsR/html/parse_ios.html
- **Android**: `29.01.18, 23:33 - Alice: Hi?` — no brackets, no seconds, ` - ` separator; media `IMG-20180129-WA0001.jpg (file attached)`; `<Media omitted>`. https://search.r-project.org/CRAN/refmans/WhatsR/html/parse_android.html
- Multi-line messages continue without a timestamp prefix; parsers must auto-detect DD/MM vs MM/DD, 2- vs 4-digit years, 12 h/24 h. https://pypi.org/project/whatsapp-chat-analyzer/ , https://pub.dev/packages/whats_json , https://docs.rs/crate/wc-parser/latest
- **[commonly reported, not verified this session]** recent iOS exports insert U+202F (narrow no-break space) before AM/PM and U+200E marks — normalise Unicode before regexing.

### Google Keep (Takeout)
One `.json` + one `.html` per note: `title`, `textContent`, `listContent[]{text, isChecked}`, `labels[]{name}`, `color`, `isArchived`, `isPinned`, `isTrashed`, `createdTimestampUsec`, `userEditedTimestampUsec`, `attachments[]{filePath, mimetype}`, `annotations[]{description, source, title, url}` (link previews). Attachments shipped as sibling files. **[community-documented; no official schema]** https://gist.github.com/ThomasHineXYZ/36b61133a2c86ffa1422ee6c3063f786 , https://forum.obsidian.md/t/google-keep-json-files-adding-yaml-meta-data/60571 , https://joplinapp.org/plugins/plugin/net.bonfigli.GoogleKeepToJoplin/

### Apple Notes
- macOS Notes: File → Export To → **PDF or Markdown**, one note at a time; no bulk export. https://support.apple.com/en-gw/guide/notes/not201900c07
- Bulk: free third-party Mac app "Exporter" (Markdown/HTML for all notes). https://zapier.com/blog/export-apple-notes.md , https://StandardNotes.org/help/31/how-can-i-import-my-notes-from-apple-notes
- iOS: no documented bulk export found. Practical path: user shares individual notes (share sheet → Shortcut) or exports from a Mac.

### Instagram "Download your information"
JSON or HTML selectable; may take up to 30 days (often minutes). Liked posts live under `your_instagram_activity/likes/liked_posts.json`; each entry = creator `title` + `string_list_data[{href, value, timestamp}]` (UTC epoch); saved posts similar, grouped by Collection; `posts_viewed.json` / `videos_watched.json` carry author + timestamp only. Keys **[community-reported, not verified against a current export]**. https://help.instagram.com/ipad-app/181231772500920 , https://stashr.me/blog/export-instagram-data , https://pirg.org/resources/how-to-request-and-download-instagram-data/

### TikTok "Download your data"
- JSON (`user_data_tiktok.json`): `"Activity" → "Like List" → "ItemFavoriteList": [{"Date","Link"}]`, `"Favorite Videos" → "FavoriteVideoList"`, `"Video Browsing History" → "VideoList"`; each item has only `Date` and `Link`. TXT variant carries less. https://gist.github.com/extratone/c6c81f022721ee9f5a85bbdc28136661 , https://www.scrolldecoded.com/blog/tiktok-data-export-guide/
- TikTok also exposes a **Data Portability API** (categories: Posts and Profile, Activity incl. "Watch History" with date/link/title, Direct Messages, Full Archive incl. "Like List", "Favourite Videos", "Comments"); "Not all features are available in all regions" (likely DMA/EEA-driven — **[unverified]**). https://developers.tiktok.com/docs/en/data-portability-data-types

---

## 9. OCR for memes/images (incl. Hindi/Devanagari)

| Option | Licence (SPDX) | Devanagari | Windows notes | Source |
|---|---|---|---|---|
| **Tesseract 5 + pytesseract** | engine Apache-2.0; `pytesseract` Apache-2.0 (since 0.3.1); `hin.traineddata` Apache-2.0 | yes (`hin`, `mar`, `nep`, `san`; `Devanagari` script model) | UB Mannheim installer, `winget install MannheimUniversityLibrary.TesseractOCR`; set `pytesseract.pytesseract.tesseract_cmd` | https://pypi.org/project/pytesseract/ , https://github.com/UB-Mannheim/tesseract/wiki , https://ports.macports.org/port/tesseract-hin |
| **EasyOCR** | Apache-2.0 | yes — Hindi/Marathi/Nepali since v1.1.5 (Jul 2020); "80+ languages" | pip, PyTorch dependency (heavy) | https://github.com/JaidedAI/EasyOCR , https://pypi.org/project/easyocr/1.1.5/ |
| **PaddleOCR** | Apache-2.0 | yes — PP-OCRv5 multilingual (109 langs) added Devanagari **2025-10-16**; PaddleOCR-VL lists "Hindi (Devanagari script)" | PaddlePaddle wheel; heavier install | https://github.com/PaddlePaddle/PaddleOCR |
| **RapidOCR** | Apache-2.0 (code + bundled models) | via PP-OCRv4/v5 multilingual models (Docling lists `devanagari` for v4/v5; v6 list lacks it) | ONNX Runtime — lightest CPU option, no Paddle/Torch | https://github.com/RapidAI/RapidOCR , https://docling-project.github.io/docling/concepts/OCR_native/ |

### Vision-LLM fallback — cost per ~1 MP meme (input side; add ~100–300 output tokens)
- **OpenAI** (tile models GPT-5/5.1: 70 base + 140/tile; GPT-4.1/4o: 85 + 170/tile; a 1024² image → 768² → 4 tiles = 765 tokens on GPT-4.1 ≈ **$0.0015** at $2/M; patch models: `ceil(w/32)·ceil(h/32)` × multiplier — gpt-4.1-mini 1024 patches × 1.62 = 1,659 tokens ≈ **$0.0007** at $0.40/M; gpt-5.4-mini $0.75/M, gpt-5.4-nano $0.20/M). https://developers.openai.com/api/docs/guides/images-vision , https://developers.openai.com/api/docs/pricing
- **Anthropic** (28-px patches: 1000×1000 = 1,296 tokens; standard tier downsizes to ≤1568 px / ≤1568 tokens): Haiku 4.5 $1/M → **$0.0013**; Haiku 5.5 $0.10/M (≤100k prompts) → **$0.00013**; Sonnet 4.5 $3/M → $0.0039; Opus 5.5 $4/M → $0.0052 ("$5.18 per thousand"). https://platform.claude.com/docs/en/build-with-claude/vision , https://platform.claude.com/docs/en/about-claude/pricing
- **Google** (258 tokens ≤384 px, else 768² tiles × 258; 1024² ≈ 4 tiles = 1,032 tokens): Gemini 2.5 Flash-Lite $0.10/M → **$0.0001**; 2.5 Flash $0.30/M → $0.0003; 3.1 Flash-Lite $0.25/M. https://ai.google.dev/gemini-api/docs/image-understanding , https://ai.google.dev/gemini-api/docs/pricing
- Practical design: local RapidOCR/Tesseract first (free, ~100 ms), vision-LLM only when OCR confidence is low or text is stylised — at $0.0001–$0.0015 per image, 1,000 memes/month is $0.10–$1.50. Hindi memes are typically **code-mixed Hinglish in Latin script** which no OCR model needs a Devanagari pack for, but the app's D-066 language contract already handles that at the prompt level.

---

## 10. Privacy / legal

### GDPR
- **Art. 20 (portability):** data "provided to a controller, in a structured, commonly used and machine-readable format", when processing rests on consent/contract and is automated. https://gdpr-text.com/read/article-20/
- **Art. 17 (erasure):** on withdrawal of consent, purpose exhausted, objection, unlawful processing; if data made public, "reasonable steps" to inform other controllers; exceptions for legal obligations/claims. https://gdpr-info.eu/art-17-gdpr/
- **Art. 12(3)/(5):** respond "within one month", extendable by two further months with notice; free of charge unless manifestly unfounded/excessive. https://gdpr-info.eu/art-12-gdpr/
- Echo implication: a hosted store must (a) export the user's own corpus (documents, Q&A, knowledge artifacts) in JSON/JSONL — the existing dataset-export endpoints are a start; (b) implement erasure that also purges Chroma vectors, transcript cache rows the tenant exclusively owns, visual frames, and backups within one month.

### India DPDP Act 2023 + Rules 2025
- Rules notified **13 Nov 2025** (G.S.R. 846(E)); phased: Rules 1, 2, 17–21 (Board) in force immediately; Rule 4 (Consent Managers) **14 Nov 2026**; substantive Rules 3, 5–16, 22 **14 May 2027** (sources vary 12/13/14 May; MeitY has floated pulling it to Nov 2026 — not notified). https://dpdpa.dcomply.in/rules/ , https://www.azbpartners.com/bank/indias-digital-personal-data-protection-act-phased-rollout-and-key-compliance-milestones/
- Rights: access, correction and erasure, nomination, grievance redressal; **"does not grant the right to data portability and the right to be forgotten"**; fiduciaries must erase when purpose is served or consent withdrawn; penalties up to ₹250 crore (security safeguards); applies to processing outside India "if it is for offering goods or services in India". https://prsindia.org/billtrack/digital-personal-data-protection-bill-2023

### "Other people's content" (WhatsApp threads, recorded conversations)
- **Limitless (ex-Rewind):** ToS requires wearers to "notify and obtain consent from individuals before recording"; white LED; "Consent Mode" voice-ID only for consenting speakers; may use data to train third-party AI models. Acquired by **Meta on 5 Dec 2025**; pendant sales ended; Rewind Mac capture disabled 19 Dec 2025; service discontinued in **EU/UK**; existing users get Unlimited free through 2026. https://help.limitless.ai/en/articles/13004190-talking-to-someone-wearing-the-pendant-what-to-expect-and-how-we-handle-your-information , https://www.limitless.ai/privacy , https://www.neowin.net/news/meta-acquires-ai-startup-limitless-ending-sales-of-its-popular-pendant-wearable , https://www.hedy.ai/post/meta-acquires-limitless-ai-privacy/
- **Reflect:** end-to-end encrypted notes and assets ("not even the Reflect team"), Doyensec audit claimed, but "ultimately you have to trust the client". No third-party-content policy beyond that. https://reflect.app/blog/encrypted-assets-lock-screen-activity-deep-links , https://team-reflect.notion.site/Security-and-encryption-89450e351e724893b72898d9acc663fe
- **Obsidian:** "All data is saved locally on your device and is never sent to our servers"; no telemetry; Sync is E2EE incl. file names. https://obsidian.md/privacy
- **Mem:** SOC 2 Type II, encrypted in transit/at rest; no documented handling of third-party content. https://www.anygen.io/showcase/mem-ai-review/index.html
- **Finding:** none of these products technically distinguishes first-party from third-party content; they shift the legal burden to the user via ToS. Echo can do better cheaply: tag each WhatsApp/email message with `author_is_tenant` and default third-party text to *context-only* (retrievable, never quoted verbatim in outputs, excluded from dataset exports) — a defensible position under GDPR legitimate interest and a clean DPDP story.

### Client-side encryption / zero-knowledge
| Library | SPDX | Notes |
|---|---|---|
| libsodium | ISC | C core; PyNaCl vendors it | https://metadata.ftp-master.debian.org/changelogs/main/p/python-nacl/oldoldstable_copyright |
| PyNaCl | Apache-2.0 | Python binding (secretbox/XChaCha20-Poly1305, sealed boxes) | https://pypi.org/project/PyNaCl/ (metadata via Debian/Cygwin pages above) |
| age (Go CLI/lib) | BSD-3-Clause | file encryption, passphrase or X25519 recipients | https://pkgs.alpinelinux.org/package/v3.22/community/x86/age |
| pyrage | MIT | Python bindings to `rage` (Rust age impl.); `passphrase.*`, `x25519.*` | https://pypi.org/project/pyrage/ |
| WebCrypto `SubtleCrypto` | W3C Recommendation, built into every browser (no licence) | AES-GCM, ECDH, PBKDF2/HKDF in the PWA | https://www.w3.org/TR/WebCryptoAPI/ |
| Transformers.js | Apache-2.0 (per repo; page truncated) | `feature-extraction` pipeline in-browser, WASM default, `device: 'webgpu'` opt-in; e.g. `Xenova/all-MiniLM-L6-v2` or a multilingual MiniLM port | https://huggingface.co/docs/transformers.js/index |

**Hard constraint:** sentence-transformers and Chroma run on the server and need plaintext. **Embeddings cannot be computed server-side on ciphertext.** A true zero-knowledge mode therefore means either (a) the browser computes embeddings with Transformers.js and uploads `{ciphertext, vector}` — the server can still index/search vectors, but vectors are themselves a lossy leak of content (embedding-inversion attacks exist), so they must be treated as personal data and the server can only ever return opaque IDs for the client to decrypt; the LLM Q&A step must then run client-side or on plaintext the client sends per request; or (b) "private-by-key" mode: server-side encryption at rest with a tenant key (Fernet already exists for BYOK, D-043) and honest messaging that the operator can read data; or (c) local-only desktop deployment. Option (b) is the only one compatible with the current LangGraph/Chroma pipeline without a rewrite.

---

## 11. Comparable products

- **Limitless / Rewind** — $99 pendant + Free / Pro (~$19–29/mo) tiers; app transcribed everything heard; Rewind recorded the Mac screen. Meta bought it 5 Dec 2025, stopped pendant sales, shut Rewind capture 19 Dec 2025, pulled out of EU/UK, and gave existing users the Unlimited plan free for 2026. Lesson: always-on capture + third-party voices made the privacy story fragile enough that the company never resolved one-party vs all-party consent and ended as an acqui-hire. https://www.outlookbusiness.com/corporate/meta-acquires-ai-wearables-start-up-limitless-as-it-doubles-down-on-personal-superintelligence , https://fast.io/resources/limitless-ai-review-2026/
- **Mem** — official pricing (Oct 2026): Free (25 messages, 25 notes/mo), Plus $9, **Pro $29**, Pro 2× $49, 5× $99, 10× $149, 20× $199/mo, "+$50/mo" extra-usage units; metered on messages, new notes, open tasks, routines, connections and Voice-Mode hours. Note-centric, cloud-only, SOC 2. https://get.mem.ai/pricing
- **Reflect** — reported flat **$10/mo**, no free tier (14-day trial per some reviews); homepage currently says Mac "No subscription required" and iOS "See local pricing on the App Store" — pricing page 404'd, so current model **[unverified]**. E2EE notes/assets, Doyensec-audited (claimed), closed source. https://www.sollmannkann.com/project-management-and-notes/mem-vs-reflect/ , https://reflect.app/
- **Personal.ai** — the pricing page now markets only an enterprise on-prem offer ("MODEL-4 is deployed on your own network under a single agreement", "Talk to Sales"); no public consumer plans found. https://www.personal.ai/pricing
- **Google NotebookLM (now "Gemini Notebook")** — official limits: Standard (free) **100 notebooks / 50 sources per notebook**; Plus 200/100; Pro 500/300; Ultra 20 TB 500/500; Ultra 30 TB 500/600; per source 500k words or 200 MB; source types: PDF, text, Markdown, audio, Docs/Slides, URLs, YouTube. Closest "curated sources" analogue to Echo; no activity connectors. https://support.google.com/notebooklm/answer/16213268
- **Apple Journal / JournalingSuggestions** — iOS 17.2+ (Dec 2023) framework; `JournalingSuggestionsPicker` surfaces moments (photos, workouts, locations, contacts, music/podcasts, state of mind); requires the Journaling Suggestions capability/entitlement; "Only suggestions explicitly added by the user will be shared with an app" — a native-only, user-picks-each-item model. Apple's docs pages fetched empty; entitlement name `com.apple.developer.journal.allow` **[unverified]**. https://techcrunch.com/2023/12/11/apples-new-journal-app-is-now-available-with-the-release-of-ios-17-2 , https://zenn.dev/mtfum/articles/journaling_suggestions?locale=en , https://developer.apple.com/documentation/journalingsuggestions
- **Microsoft Recall** — launched May 2024 as default-on screenshot capture with an unencrypted SQLite DB (TotalRecall PoC); withdrawn, relaunched **opt-in only**, Windows Hello ESS re-auth per use, snapshots + index encrypted with just-in-time decryption (VBS enclave), sensitive-info filter on by default, per-app/site exclusions, full removal via Windows Features, removed by default on managed devices; still probed (TotalRecall Reloaded, Apr 2026) and Signal/Brave/AdGuard added screenshot-blocking. Lessons for Echo: opt-in per connector, visible capture indicator, exclusion lists, one-click purge, and never a plaintext index. https://support.microsoft.com/en-us/windows/retrace-your-steps-with-recall-aa03f8a0-a78b-4b3e-b0a1-2eb8ac48701c , https://therecord.media/microsoft-reverses-course-recall-opt-in , https://doublepulsar.com/microsoft-recall-on-copilot-pc-testing-the-security-and-privacy-implications-ddb296093b6c

---

## Recommended connector order (cheapest / lowest privacy weight first)

| # | Connector | Mode | Why here | Feasible via API? |
|---|---|---|---|---|
| 1 | **Manual quick-share + drag-drop + paste** (URL, text, image → OCR) | push | No OAuth, no vendor policy, exercises the whole intake→document→embed path; images reuse RapidOCR/Tesseract + vision-LLM fallback | n/a |
| 2 | **Google Takeout: YouTube `watch-history.json` + `subscriptions.csv`** | file import | Zero verification; the *only* non-restricted route to watch history; schema is stable and documented by Google's My Activity reference; dedups straight into the existing `documents` library by video ID | **No** (Data API has no history; Data Portability scope is restricted) |
| 3 | **Spotify Extended streaming history (JSON) + Account data** | file import | Lifetime history with URIs; no API caps | API: 50-item tail only, dev-mode 5 users |
| 4 | **GitHub own-activity** | pull (existing OAuth + fine-grained PAT) | No verification, 5k/h; low privacy weight (mostly public data); 30-day/300-event window means a nightly Celery beat | Yes |
| 5 | **Goodreads CSV, Letterboxd CSV, Strava bulk export, Apple Health `export.xml`** | file import | APIs are dead (Goodreads), refused for LLM/personal use (Letterboxd), AI-prohibited + paid (Strava), non-existent (Apple Health). Stream-parse Health XML | **No — export only** |
| 6 | **WhatsApp .txt/.zip, Google Keep Takeout, Apple Notes (Markdown/HTML via Exporter), Instagram/TikTok JSON** | file import | Pure parsers; introduces the `author_is_tenant` third-party-content flag (WhatsApp) and the OCR path (media) | **No public APIs for user likes/notes** (TikTok Data Portability API exists but eligibility unclear) |
| 7 | **YouTube Data API `youtube.readonly`** — liked videos (≤1,000), subscriptions, playlists | pull | Sensitive-scope verification only (3–5 days, demo video, privacy policy); reuses existing Google OAuth client; 10k units/day is ample | Yes (not history) |
| 8 | **Google Calendar `calendar.readonly`** | pull | Sensitive, same verification bundle as #7; add both scopes in one review | Yes |
| 9 | **Android PWA share target + iOS Shortcut + browser-extension context-menu capture** | push | Android: manifest only; iOS: ship a Shortcut file; extension: `contextMenus`+`activeTab`, no `history` permission → lighter CWS review | Yes |
| 10 | **Email-in inbox** — self-host: IMAP polling (App Password / any IMAP provider); SaaS: Mailgun free route or Cloudflare Email Routing → Worker → Echo webhook | push | $0 entry; HMAC-verify webhooks; strip signatures/quoted replies | Yes |
| 11 | **Spotify live tail** (recently-played, saved tracks) | pull | Only for self-host single-user installs (Premium owner, 5-user allowlist); never a SaaS feature | Yes, constrained |
| 12 | **Browser history (extension `history` permission)** | pull | Heavy install warning + 2026 Limited-Use regime; prefer #9's explicit capture; if built, make it opt-in per domain with on-device filtering | Yes (Chrome, Firefox desktop; not Firefox Android/Safari) |
| 13 | **Gmail read-only** | pull | Restricted scope → CASA every 12 months; defer until there is revenue; self-host users can BYO GCP project (Testing mode) or IMAP+App Password | Yes, at CASA cost |
| 14 | **Google Data Portability API (`myactivity.youtube`, `chrome.history`)** | pull | Would give scheduled 24-h incremental watch-history pulls, but restricted + annual re-verification + billing; only worth it after Gmail-level CASA is already being paid for | Yes, restricted |
| — | **Strava API, Letterboxd API, Goodreads API, Apple Health/HealthKit web** | — | **Not feasible / not permitted for an LLM product** — export import only | **No** |

Design notes that fall out of this order:
- Every file-import connector shares one `ExportArchiveImporter` (ZIP → sniff → per-format parser → `Document` rows with `source_type` ∈ {youtube_history, spotify_stream, whatsapp_message, keep_note, …}) and calls `visibility_service.grant` exactly like today's ingest paths (D-063).
- The `EchoConnector` registry's `authorize_url / revoke / sync / supported_kinds` fits GitHub, YouTube, Calendar, Spotify; file importers need a different shape (`accepts(filename) / parse(stream)`), so register them as a second kind rather than faking `authorize_url`.
- Store `activityControls`/`reason_end`/`platform` etc. as JSON metadata, not columns — the schemas drift per export date.

---

## Risks and open questions

1. **Google verification is per-project, not per-scope**: adding `youtube.readonly` + `calendar.readonly` to the existing login client triggers sensitive-scope review for the whole consent screen; the login-only flow keeps working meanwhile, but plan a separate OAuth client for connectors if a rejection must not break sign-in.
2. **100-user lifetime cap** on unverified sensitive scopes is irreversible; do not ship YouTube/Calendar connectors to beta users before verification completes.
3. **7-day refresh-token expiry for Testing-mode apps** (claimed by Nylas/Unipile) was not confirmed in Google docs — verify empirically before recommending the "BYO GCP project" self-host path for Gmail.
4. **Data Portability API region availability** page 404'd; eligibility and per-export quota unknown.
5. **Spotify**: whether a self-host operator's Premium lapse should disable the connector gracefully; the rumoured 6-month authorisation lifetime (Jun 2026) is unverified; per-account shared quota numbers are unpublished.
6. **Strava §5.3 applies to API data only** — confirm with counsel that a user-uploaded bulk export is outside the API Policy (it is user-owned data obtained under Strava's export/GDPR feature, not "Strava API Materials").
7. **WhatsApp exports contain third-party personal data**; under GDPR the tenant is arguably the controller for a household-use exemption, but a SaaS operator is a processor — write the DPA accordingly and default third-party text to context-only.
8. **Instagram/TikTok/Goodreads/Letterboxd export schemas are undocumented** and change silently; keep parsers tolerant and ship sample fixtures; the Instagram key names above are community-reported only.
9. **Apple Health export size** (1–2 GB XML) will exceed any web-upload limit — needs chunked upload or a desktop/CLI importer; streaming parser mandatory.
10. **Chrome Web Store Aug-2026 Limited-Use enforcement** may treat a research-wiki extension that also captures page text as "collecting web browsing activity"; the listing must describe capture as the user-facing single purpose, with in-product consent.
11. **iOS share target**: no Apple commitment found; the Shortcut workaround requires users to install a `.shortcut` file and trust an HTTP action — document the token-rotation story.
12. **Zero-knowledge mode** cannot coexist with the server-side LangGraph Q&A pipeline; decide whether "private-by-key" (server-readable, tenant-key-encrypted at rest) is an acceptable product promise, and label it honestly.
13. **DPDP timeline uncertainty** (substantive duties May 2027 vs a floated Nov 2026 pull-forward) — track MeitY notifications; note DPDP has no portability right but GDPR does, so the export feature is GDPR-driven.
14. **CASA cost is lab-dependent** ($540/yr to $40k) and the assessment scope expands with each new restricted scope — budget it as a recurring line before adding Gmail or Data Portability.
15. **Vision-LLM OCR of memes sends third-party images to a provider** — needs the same provider-choice/BYOK controls as text (D-043) and should be off when the tenant selects a local-only LLM.
