# S-3.7.2 part 2 — reading shared images, recordings and PDFs: measurements (2026-10-19)

**Status:** measured, not pre-registered. The two OCR thresholds and the thread count were set from the first run below, so they fit these images by construction. The live run that follows used the settled values and was not tuned after it.

**What this can and cannot show.** The images are rendered, not photographed: one font per script, one size, and one synthetic degradation (a 4° rotation, a 1.2 px blur and noise). That is enough to see which script the on-device engine can read at all, and how far apart confident and unconfident readings sit. It says nothing about real phone photos, handwriting, or crowded screenshots with icons and avatars. The voice memo is Windows text-to-speech, so its one error is partly the synthesiser's.

## 1. On-device OCR (RapidOCR 1.4.4, default models)

The default models are PP-OCRv4 Chinese and English. The question was whether they read Devanagari, and where to draw the line between a reading to keep and one to send to the vision model.

| Image | Characters | Read | Mean box score | Accuracy |
|---|---|---|---|---|
| English post, clean | 158 | 158 | 0.988 | 1.000 |
| English post, degraded | 158 | 158 | 0.978 | 0.981 |
| English quote, clean | 64 | 64 | 0.986 | 1.000 |
| English quote, degraded | 64 | 63 | 0.980 | 0.976 |
| Hindi paragraph, clean | 82 | 0 | none | 0.000 |
| Hindi paragraph, degraded | 82 | 39 | 0.692 | 0.000 |
| Mixed Hindi-English, clean | 79 | 43 | 0.868 | 0.541 |
| Mixed Hindi-English, degraded | 79 | 59 | 0.818 | 0.420 |

Accuracy is the similarity ratio of the whitespace-free texts. The degraded Hindi image was read as Latin and Chinese noise.

**Settled.** The default models cannot read Devanagari. A reading counts as confident at 20 or more characters with a mean box score of at least 0.90 (`ECHO_OCR_MIN_CHARS`, `ECHO_OCR_MIN_CONFIDENCE`). Every English reading sits at 0.978 or above, and every Hindi or mixed reading sits at 0.868 or below.

**Not done.** A Devanagari recognition model for RapidOCR exists (PaddleOCR's `devanagari_PP-OCRv3_rec`, converted to ONNX), but it is a separate download. Without it a local-only tenant's Hindi images cannot be read. That is the follow-up, and it needs its own measurement.

## 2. OCR speed and threads

onnxruntime defaults to one thread per logical core. On this 32-thread machine that oversubscribes, and detection dominated the time.

| Threads | 1080×1920 screenshot, seconds per image (3 runs) |
|---|---|
| default (32) | 6.05, 6.02, 6.09 |
| 8 | 1.49, 1.56, 1.44 |
| 4 | 1.45, 1.36, 1.37 |
| 2 | 2.06, 2.12, 2.11 |

**Settled.** `ECHO_OCR_THREADS = 4`, with one inter-op thread.

## 3. The vision fallback on the images the local engine could not read

Each model read each image once with the shipped prompt, at reasoning off.

| Image | gpt-5.4-mini | gemini-3.1-flash-lite |
|---|---|---|
| Hindi, clean | 0.982 | 0.969 |
| Hindi, degraded | 0.932 | 0.975 |
| Mixed, clean | 1.000 | 1.000 |
| Mixed, degraded | 1.000 | 0.987 |
| **Mean** | **0.979** | **0.983** |

Four images and one read each, so the two models are tied. **Settled:** the default stays `gpt-5.4-mini`, because every install has an OpenAI key and only some have a Google key. `gemini-3.1-flash-lite` is a sound override. Both kept the Devanagari in its own script, as the prompt asks.

## 4. The full pipeline (scratch database and Chroma, real calls)

| Share | Reader | Accuracy | Notes |
|---|---|---|---|
| English post, clean and degraded | local OCR | 1.000, 0.981 | no vision call |
| Hindi paragraph, clean and degraded | vision (gpt-5.4-mini) | 0.963, 0.938 | local scores 0.0 and 0.692 sent them on |
| Mixed Hindi-English, clean and degraded | vision (gpt-5.4-mini) | 1.000, 0.987 | local scores 0.868 and 0.818 |
| Voice memo, 10.6 s, own words | Whisper | 0.959 | "Smoot Hawley" came back as "smooth-haulie" |
| PDF, 3 pages, one blank | text layer | exact | "2 of 3 pages had text" |

All eight shares were embedded into `shares_global` under the test tenant. Raw numbers are in [2026-10-19-s372-share-ocr-results.json](2026-10-19-s372-share-ocr-results.json).
