# Echo import fixtures (S-3.7.5)

Small exports in the formats the importers read. Test them in `tests/test_routers/test_echo_imports.py`.

| File | Format | What it exercises |
|---|---|---|
| `whatsapp_ios_chat.txt` | iOS `_chat.txt` | `[dd/mm/yy, h:mm:ss PM]` headers. There is a narrow no-break space (U+202F) before AM/PM. Left-to-right marks (U+200E) flag system lines and media. It also has an `<attached: …>` photo, an edited message, a deleted one, a continuation line and Devanagari text. 13/02 makes it day-first |
| `WhatsApp Chat with Asha.txt` | Android | `dd/mm/yyyy, HH:MM - ` headers. There is a system line with no sender, `<Media omitted>`, a `(file attached)` image and a three-line message. A 34-minute gap splits one sender's messages into two turns |
| `WhatsApp Chat with Sam.txt` | Android, US locale | Month-first, 12-hour clock |
| `WhatsApp Chat with Kiran.txt` | Android | No date decides the order, so the preview warns |
| `keep/*.json` | Google Takeout Keep | A pinned note with labels and a web link, an archived checklist, a trashed note, and an image-only note with no text. The tests zip them under `Takeout/Keep/` |

The WhatsApp files contain invisible characters that editors drop silently: U+200E and U+202F. To regenerate or change them, write them from Python with explicit escapes, not in an editor:

```python
LRM, NNBSP = "‎", " "
line = f"[12/02/24, 9:08:02{NNBSP}PM] Rahul: {LRM}image omitted"
```
