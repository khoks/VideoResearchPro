---
status: measurement note
captured: 2026-10-25
relates_to: S-1.11.11 (E-1.11, R5), T-1.11.11.1–3, D-051, D-080
data: 2026-10-25-caption-track-choice.json
---

# Caption-track choice: measured before fixing (S-1.11.11)

The S-1.16.2 held-out evaluation found 2 of 13 Hindi-speech videos ingested
as machine-dubbed caption tracks ([code-mixing note, section 11](2026-10-19-code-mixing-detection.md#11-end-to-end-evaluation-on-held-out-sources-t-11626)).
This note records what the caption tracks of the library's Hindi, Hinglish
and Kannada videos actually look like, what the old rule chose, and what the
new rule chooses. Raw data and per-video choices:
[2026-10-25-caption-track-choice.json](2026-10-25-caption-track-choice.json).

## 1. Method

- **Videos:** all 30 videos of the three Hinglish topic jobs (`fed18081`,
  `84a13d8d`, `f3532fa1`, approved and unapproved), plus every other library
  video stored in a non-English language: 37 in total.
- **Caption tracks:** the player response `youtube-transcript-api` already
  fetches, read in full (`backend/scripts/measure_caption_tracks.py`): each
  track's code, manual or ASR, `vssId`, and the player's `audioTracks`.
- **Declared language:** `snippet.defaultAudioLanguage` from `videos.list`,
  one call for all 37 ids (1 quota unit). `captions.list` (50 units per
  video) was not used.
- **Pacing:** one listing every 4.0 s (above `YOUTUBE_TRANSCRIPT_RATE_LIMIT`,
  D-051); the run would stop at the first IP-block signal. None occurred.
  Two videos failed to list (one `TranscriptsDisabled`, one dropped
  connection), leaving 35.
- Nothing was written to the database, not even the quota log.

## 2. What the tracks look like

| | Videos |
|---|---|
| One caption track only | 25 of 35 |
| More than one track | 10 |
| Several audio tracks (auto-dubbed) | 12 |
| No `defaultAudioLanguage` declared | 6 of 37 (including `v6CuYULP3tM`, one of the two known dubs) |

**Auto-dubs are visible in the player response, and nowhere else.** Every
multi-audio video lists its audio tracks as `<language>.<n>`. On all 12,
exactly one track ends `.4`, and it is always the default track. Every other
track ends `.10`: those are the auto-dubs. YouTube adds an ASR caption track
for some dubs, and that track's code is **exactly** the dub's code
(`en-US.10` becomes caption track `en-US`, `bn.10` becomes `bn`; this holds
for all 20 dubs of `8Hdx8IGL1sc`). The original audio's ASR track carries the
language the recogniser heard, usually as a bare code (`en-US.4` becomes `en`).

**Matching dubs on the exact code, not the language, is required.**
`IcVYyF3EEbk` has original audio `hi.4`, a dub `en-US.10`, and a single
caption track, `en`. That track belongs to the original audio. It is an
English-heavy Hinglish podcast, and the uploader declared `en-IN`. Matching
on the primary subtag (`en`) would discard the video's only real track.

**The uploader's declaration and the recogniser can disagree.** Three
Hinglish podcasts declare English (`en-IN`, `en`) and have only a `hi` ASR
track (`HVkSGvZi-WY`, `8RCOFdilri4`, `IbcYNtZ8HZY`). One video declares `en-IN`
while its original audio track is `hi.4` (`IcVYyF3EEbk`). Where both a
declaration and a player original exist (10 videos), they agree on the
language in 9.

**`snippet.defaultLanguage` is not a speech signal.** It is the language of
the title and description. It reads `en` on `v6CuYULP3tM`, a Hindi-speech
video.

## 3. Old rule against new rule

Old rule: `fetch(languages=[en, en-auto, en, en-auto])`, then the first
listed track. New rule (`youtube_service.plan_caption_track` and
`choose_caption_track`):

1. Drop every ASR track whose code exactly matches a dubbed audio track.
2. Find the spoken language: the first of these that some remaining track
   is in (`resolve_spoken_language`). A signal with no track in its language
   is passed over, not taken as the answer.
   1. `defaultAudioLanguage`. It is looked up only when the remaining
      tracks span more than one language, since otherwise the choice cannot
      change, and at most once per fetch, however many attempts run.
   2. The player's original audio track, on a multi-audio video.
   3. On a single-audio video, the language of its ASR track. With one
      audio track there is nothing to dub, so the ASR track is the
      recogniser run on the only audio. This is what keeps a failed lookup
      (quota spent, key or network error) or a missing declaration from
      handing `C6YtPJxNULA` to its creator's English translation.
3. Take a track in the spoken language: a manual track first, then the ASR
   track.
4. Only when the spoken language is unknown or has no track, fall back to
   English first, then the remaining ASR track (the original audio's), then
   whatever is left.
5. If every track is a dub, take none. The fetch goes to Whisper (which hears
   the original audio) or is recorded unavailable.

The two rules differ on 7 of the 35 videos:

| Video | Tracks | Old | New | Why |
|---|---|---|---|---|
| `1v3_AQ26jZ0` | bn, en-US, hi (all ASR) | **bn** (stored) | hi | `bn` and `en-US` are dubs of `hi.4` |
| `5AuuOZ4vuxI` | bn, en-US, hi | **bn** (stored) | hi | same |
| `v6CuYULP3tM` | en-US, hi | **en-US** (stored) | hi | `en-US` is the dub; nothing declared, so the player's original decides |
| `81ymPYEtFOw` | bn, hi | bn | hi | `bn` dub (not yet fetched) |
| `ltr-znVaqgc` | en-US, hi | en-US | hi | `en-US` dub (not yet fetched) |
| `C6YtPJxNULA` | en (manual), hi | en (manual) | hi (ASR) | declared `hi`; the manual English track is the creator's translation |
| `Fi_kMc6hLxI` | en, en-IN (manual) | en (ASR) | en-IN (manual) | same language, the manual track now wins |

The new rule needed a Data API lookup for 2 of the 35 videos (`C6YtPJxNULA`,
`9tigHWH-UD8`). For the rest, at most one language remained, so the
declaration could not change the choice.

Choices the new rule keeps, deliberately:

- **`9tigHWH-UD8`** declares `en` and has a manual `en` track plus a `hi`
  ASR track. The manual English track is chosen because it matches the
  declaration. If the speech is mostly Hindi, that track is a translation.
  The recogniser heard `hi`, but on Hinglish speech the two signals are
  equally plausible, so the declaration comes first while a track is in it.
  If the lookup fails or the video declares nothing, the ASR track's `hi`
  decides.
- **The English-first fallback when the spoken language is unknown** (the
  brief). It only applies when no declaration with a track is available, the
  video has a single audio track, and that track has no ASR track (or ASR
  tracks in more than one language).

## 4. The re-fetch dry run (T-1.11.11.3)

`backend/scripts/refetch_dubbed_transcripts.py` was run against the whole
library in dry-run mode. It skips Whisper transcripts, reads declarations for
the rest (2 units, not logged) and lists the caption tracks of every
remaining row.

The first run (2026-10-25) listed only where a dub seemed possible: no
declaration, or a cached language that differed from the declared one. That
skipped 75 rows as "cached in the declared language". But a declaration is
no proof: 4 of the 37 measured Hindi videos declare English, and an `en-US`
dub cached under an `en-IN` declaration shares its primary subtag. So the
skip was removed, and the run was repeated on 2026-10-29 with every
candidate listed:

| | Count |
|---|---|
| Cached transcripts skipped as Whisper (`source='whisper'`, or a language name such as `english` on pre-provenance rows) | 134 |
| YouTube-caption candidates, all listed (paced 4.0 s, about 6 minutes, no IP-block signal, no listing failure) | 93 |
| ...of which the first run had skipped as cached in the declared language | 74 (all confirmed in the spoken language) |
| Already in the spoken language | 90 |
| Every track a dub (owner decision: no caption track can replace them) | 0 |
| **Would be re-fetched** | **3**: `1v3_AQ26jZ0` (bn → hi), `5AuuOZ4vuxI` (bn → hi), `v6CuYULP3tM` (en-US → hi) |

The spoken language came from the declaration on 76 rows, the player's
original audio on 11, and the ASR track of a single-audio video on 6. All 93
matched a track in the spoken language.

None of the three has a knowledge report. The write mode (`--write`) is the
owner's step. It re-fetches the three, then, for each:

1. chunks the new text before writing anything;
2. deletes the old chunks, and stops (writing nothing) if Chroma reports the
   delete failed;
3. writes the `transcript_cache` row and the document in one transaction;
4. inserts the new chunks.

A failure at any step leaves a state the next run lists again, or the next
job re-embeds from the cache. The pass stops at the first IP-block signal.
Re-embedding Hindi chunks runs `code_mixing_render_english` (an LLM call,
D-084) while `CODE_MIX_ENGLISH_RENDERING_ENABLED` is on.

## 5. What this does not cover

- **A dub whose code equals the original's ASR code.** For example, a `hi.10`
  dub on a video whose recogniser labels the original audio `hi`. The rule
  would then drop the original's track as a dub, and the fetch would go to
  Whisper instead of ingesting anything doubtful. No video in the sample had
  this.
- **Creator-uploaded multi-language audio** (not auto-dubbed) was not in the
  sample. The `.4` suffix might not hold there. The fallback is the player's
  default audio track, and every non-original track is still treated as a
  dub, which is the right reading for speech the speaker did not produce.
- **Whisper's audio track.** When every caption track is a dub, the fetch now
  goes to Whisper. yt-dlp ranks the track marked "original" first, but no
  dubbed video went through Whisper in this measurement (yt-dlp has been
  bot-walled on this machine since S-1.16.2).
