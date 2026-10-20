# Echo import fixtures (S-3.7.5)

Small exports in the formats the importers read. The share importers (WhatsApp, Keep) are tested in `tests/test_routers/test_echo_imports.py`, the event importers and Apple Health in `tests/test_routers/test_echo_event_imports.py`.

| File | Format | What it exercises |
|---|---|---|
| `whatsapp_ios_chat.txt` | iOS `_chat.txt` | `[dd/mm/yy, h:mm:ss PM]` headers. There is a narrow no-break space (U+202F) before AM/PM. Left-to-right marks (U+200E) flag system lines and media. It also has an `<attached: …>` photo, an edited message, a deleted one, a continuation line and Devanagari text. 13/02 makes it day-first |
| `WhatsApp Chat with Asha.txt` | Android | `dd/mm/yyyy, HH:MM - ` headers. There is a system line with no sender, `<Media omitted>`, a `(file attached)` image and a three-line message. A 34-minute gap splits one sender's messages into two turns |
| `WhatsApp Chat with Sam.txt` | Android, US locale | Month-first, 12-hour clock |
| `WhatsApp Chat with Kiran.txt` | Android | No date decides the order, so the preview warns |
| `keep/*.json` | Google Takeout Keep | A pinned note with labels and a web link, an archived checklist, a trashed note, and an image-only note with no text. The tests zip them under `Takeout/Keep/` |
| `takeout_youtube/` | Takeout YouTube history (JSON) | Watch history with an ad (has `details`), a removed video and a Hindi-locale entry; search history in English and Hindi. Zipped under `Takeout/YouTube and YouTube Music/history/`, with the Keep notes beside them |
| `spotify/Streaming_History_Audio_2024.json` | Spotify extended streaming history | A track, a skipped track, a podcast episode and a private-session play; every row carries `ip_addr` and `conn_country`, which must not be stored |
| `StreamingHistory_music_0.json` | Spotify account data (one year) | The short format: `endTime`, `artistName`, `trackName`, `msPlayed` |
| `goodreads_library_export.csv` | Goodreads library export | Read, currently-reading and to-read shelves, a review with `<br/>`, private notes, Excel-style `="…"` ISBNs |
| `letterboxd/*.csv` | Letterboxd export | A rewatch in the diary, a review, a film in `watched.csv` with no diary date (rated in `ratings.csv`) and a watchlist entry. Zipped as `letterboxd-<user>-<date>.zip` |
| `strava/` | Strava bulk export | `activities.csv` with its duplicated column names (the first of each pair is read) and a `.gpx` route, which the importer must never open. Zipped as `export_<n>.zip` |
| `apple_health/export.xml` | Apple Health | Sleep recorded by a watch and a phone (the larger wins), an in-bed record, a nap that must not count as a night, steps from two sources, a heart-rate record, workouts in minutes and in seconds |

The WhatsApp files contain invisible characters that editors drop silently: U+200E and U+202F. To regenerate or change them, write them from Python with explicit escapes, not in an editor:

```python
LRM, NNBSP = "‎", " "
line = f"[12/02/24, 9:08:02{NNBSP}PM] Rahul: {LRM}image omitted"
```
