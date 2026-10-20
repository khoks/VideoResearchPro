# S-3.7.5 part 1 — export imports at realistic sizes (2026-10-19)

**What was measured.** Synthetic WhatsApp chats in the Android format, two participants, with message gaps drawn from 0 minutes to 10 hours and 2 to 18 words per message. They ran through preview, import, embedding and undo against a scratch SQLite database and a scratch Chroma directory. The machine has 32 logical cores, and everything runs on the CPU.

**What it cannot show.** Real chats have longer messages, more media and other locales. The turn counts depend on the gap distribution chosen here. The timings are for one machine.

## Parsing (preview: date-order check plus one full pass)

| Chat | Size | Seconds | Python heap peak |
|---|---|---|---|
| 200,000 messages | 17.9 MB | 21.6 (under `tracemalloc`, which slows Python roughly threefold) | 0.1 MB |
| 1,000,000 messages | 89.4 MB | 19.0 | not traced |

Memory stays flat because the parser reads line by line from the spooled upload. The first version took 4.1 s for an 8.3 MB chat. Building the translate table once and precompiling the time regexes brought that to 1.6 s. So did counting during the turn-grouping pass instead of in a second pass.

## Import, embedding, undo

| Step | Size | Before | After |
|---|---|---|---|
| Import (preview, parse, insert) | 200,000 messages, 133,562 turns | 52.3 s (ORM inserts) | 27.1 s (one `executemany` per 1,000 rows) |
| Embedding (`echo.embed_import`) | 2,641 turns | — | 49.9 s, 18.9 s per 1,000 |
| Undo, embedded | 2,641 turns and vectors | 54.1 s (one `delete_share` per share) | 3.8 s (`delete_shares` in bulk) |
| Undo, not yet embedded | 124,901 turns | 95.7 s (bulk, tenant in the `WHERE`) | 7.0 s (primary-key lookup, tenant checked in Python) |

The large undo was quadratic at first. With `tenant_id` in the `WHERE` clause, SQLite chose the tenant index and scanned every row of the tenant once per 900-id chunk.

Embedding is bound by the embedder. `paraphrase-multilingual-MiniLM-L12-v2` encodes about 108 short texts a second on this machine, and changing the torch thread count does not raise that; 4 threads is slower. Upserting into Chroma doubles the cost. So a ten-year chat of about 130,000 turns indexes in roughly 40 minutes, in the background, with progress on the imports page. The shares are browsable as soon as the import returns.

## Settled

- The 200 MB upload cap (`ECHO_IMPORT_MAX_BYTES`) holds about 2 million messages. Parsing it takes about 45 s per pass, and an import makes two passes.
- Import and undo run in the request; embedding runs in the background.
- One cascade serves every delete path. `delete_share` now calls `delete_shares`, so anything added to the cascade later, such as voice-signal tombstones, covers undo as well.

## Part 2 — event importers and Apple Health

**What was measured.** Synthetic exports in each service's format against a scratch SQLite database: Spotify's extended streaming history (200,000 plays in files of 16,000, 2% private-session), a Takeout `watch-history.json` (100,000 entries), and Apple Health `export.xml` files with a day's records as a watch and phone write them (200 step samples from two sources, 500 heart-rate samples with metadata, 600 active-energy samples, 20 sleep-stage segments, a workout every other day). Same machine as part 1. Real exports have more record types; the per-record costs should carry over.

### Apple Health parse

| Export | Records | Size | Seconds | Peak working set |
|---|---|---|---|---|
| One year, as first written | 481,800 | 136 MB | 2.1 | 86 MB (36 MB before the parse) |
| Five years, as first written | 2,409,000 | 679 MB | 32.0 | 266 MB |
| Five years, root cleared | 2,409,000 | 679 MB | 23.0 | 50 MB |

`iterparse` with `elem.clear()` is the usual advice, and it is not enough: a cleared element stays in its parent's child list, so memory grew by about 95 bytes a record. A ten-year export of 20 million records would have needed 2 GB. Clearing the root after each top-level element holds memory flat. What remains is the per-day totals and the sleep segments, about 14 MB for five years. A test pins it: the root has no children after a parse.

### Event import, re-import, undo

| Step | Spotify, 196,033 plays (5.2 MB zipped) | Takeout, 100,000 watches (2.3 MB zipped) |
|---|---|---|
| Preview | 4.4 s | 2.0 s (3.7 s before the URL fast path) |
| Import, ORM rows, a commit every 200 | 53.1 s | 43.0 s |
| Import, one `executemany` and commit per 1,000 | 33.3 s | 23.4 s |
| Re-import (all already held) | 9.0 s | 5.3 s |
| Undo | 4.4 s | 8.8 s |

A commit costs about 25 ms here, so S-3.2.1's 200-row batches spent 25 s of a 200k-event import on commits alone. The writer now inserts new rows with one `executemany` and takes a `batch_size`, which the importers set to 1,000; its default, and so the API connectors' behaviour, is unchanged. Parsing ran twice (preview, then import), and for Takeout a third of it was `urlsplit` and `parse_qs` on each URL; nearly every entry is a plain `https://www.youtube.com/watch?v=` address, which now takes a fast path. What is left is SQLite maintaining three indexes on a growing table. A heavy listener's lifetime history imports in well under a minute, in the request, as in part 1.
