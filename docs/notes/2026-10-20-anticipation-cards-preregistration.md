---
status: pre-registered 2026-10-20, before any card was built or shown
story: S-3.8.2 (E-3.8)
---

# Anticipation cards: frequency cap and dismissal rule, pre-registered

The Echo panel (S-3.8.1) can offer one-line next steps ("anticipation cards"). A surface that offers things unasked can turn into a nag. These rules are fixed **before** the cards exist, so they cannot be tuned to make a card look welcome after the fact. Changing any number below needs a new note and a decision entry, not an edit to this one.

## The three kinds

| Kind | What it says | Key (one card per key) | Acting on it |
|---|---|---|---|
| `saved_search` | A saved search's answer changed (an unread S-8.3.3 notice). | `saved_search:<notification id>` | Opens the notice's link and marks the notice read. |
| `shares` | Shares were read since the user last opened the inbox ("2 screenshots and a voice note"), and how many need a retry. Direct shares only; imports never count. | `shares:<id of the newest of them>` | Opens the shares inbox. |
| `questions` | Up to three "You might ask" questions for the page in view (S-8.4.1). The context is `job:<id>` on a run, `document:<id>` on a knowledge page, and `library` elsewhere. | `questions:<context>` | Puts the question in the panel's Ask field. |

## Rule 0: where cards may appear

- Only inside the Echo panel, and only after the user opened it.
- Never a popup, toast, sound, push, email, badge or dot on the bubble.
- Cards sit above the conversation while the panel's conversation is empty. Once the user asks or drafts something in that panel session, they step aside.

## Frequency cap

1. At most **3 cards** per panel view, at most **one per kind**, in the order `saved_search`, `shares`, `questions`.
2. A card (its key) is shown on at most **3 distinct days**. After that it stays hidden. New content has a new key: another notice, newer shares, another page.
3. "Shown" is counted once per key per calendar day (UTC), however often the panel opens.
4. *Added before the first card shipped, 2026-10-20, from the live check:* a card counts as shown only if it rendered. A questions card is counted when the panel puts at least one question on screen. An empty library has none, and counting those views would understate the act rate.

## Dismissal rule

1. **×** on a card hides that key for good.
2. **Acting** on a card also retires its key. It does not count as a dismissal.
3. Dismissing **3 cards of one kind within 30 days** turns that kind off. The panel says so once ("You dismissed three of these, so they are off. Turn back on"), and the card settings in the panel can turn it back on at any time.
4. The user can turn any kind off or on directly, without dismissing anything.

## What is recorded, and how it will be judged

Everything lives in one Echo table, `echo_card_state`, per tenant and per key: days shown, last day shown, dismissed at, acted at. There is one row per muted kind (`mute:<kind>`) and the inbox-seen marker (`seen:shares`). It is exported and erased with the brain (D-089).

After 30 days of use, read per kind:
- **act rate** = keys acted on / keys shown;
- **dismiss rate** = keys dismissed / keys shown.

Pre-registered reading:
- A kind with a dismiss rate above **50%**, or an act rate below **10%**, over at least 20 shown keys, is switched **off by default**.
- A kind meeting neither condition stays on.
- Nothing adjusts itself automatically; the reading is a script and a decision entry.

## Not decided here

The wording of each card and its visual weight; those are UI choices, free to change. This note fixes only how often cards appear and how dismissal works.
