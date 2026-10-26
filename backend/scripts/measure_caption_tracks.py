"""Measure which caption tracks a video offers against the language it is
spoken in — S-1.11.11, read-only.

For each video the script records:

* the caption tracks YouTube lists (language code, display name, manual or
  ASR, ``vssId``, translatable), read from the same player response
  ``youtube-transcript-api`` parses, plus the player's ``audioTracks``;
* the Data API's ``snippet.defaultAudioLanguage`` and
  ``snippet.defaultLanguage`` (``videos.list``, 1 quota unit per 50 ids —
  never ``captions.list``, which costs 50 units per video);
* the language the library currently stores for the video.

It writes nothing to the database: documents are read, the quota log is not
touched (the single ``videos.list`` call is issued directly, so it is not
recorded in ``api_quota_log``), and no transcript is fetched or cached.

Listing is paced at ``YOUTUBE_TRANSCRIPT_RATE_LIMIT`` or slower (D-051) and
the run stops at the first IP-block signal.

Usage (run from the main checkout's ``backend`` so settings load its .env):
    ./venv/Scripts/python <worktree>/backend/scripts/measure_caption_tracks.py \
        --job-prefixes fed18081,84a13d8d,f3532fa1 --non-english-library \
        --out <path>.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.job_video import JobVideo  # noqa: E402
from app.services import youtube_service  # noqa: E402

_ENGLISH = {"en", "english"}


def _collect_video_ids(job_prefixes: list[str], non_english: bool) -> list[dict]:
    """Return [{video_id, stored_language, title}] read from the library."""
    db = SessionLocal()
    try:
        rows: dict[str, dict] = {}
        for prefix in job_prefixes:
            q = (
                db.query(Document.video_id, Document.transcript_language, Document.title)
                .join(JobVideo, JobVideo.document_id == Document.document_id)
                .filter(JobVideo.job_id.like(f"{prefix}%"))
                .filter(Document.source_type == "video")
            )
            for vid, lang, title in q:
                if vid:
                    rows.setdefault(vid, {"video_id": vid, "stored_language": lang, "title": title})
        if non_english:
            q = db.query(Document.video_id, Document.transcript_language, Document.title).filter(
                Document.source_type == "video",
                Document.transcript_language.isnot(None),
            )
            for vid, lang, title in q:
                if vid and (lang or "").lower() not in _ENGLISH:
                    rows.setdefault(vid, {"video_id": vid, "stored_language": lang, "title": title})
        return list(rows.values())
    finally:
        db.close()


def _audio_languages(video_ids: list[str]) -> dict[str, dict]:
    """``videos.list`` snippet languages, batched 50 ids per unit."""
    youtube = youtube_service.get_youtube_client()
    out: dict[str, dict] = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        response = youtube.videos().list(
            part="snippet",
            id=",".join(batch),
            fields="items(id,snippet(defaultAudioLanguage,defaultLanguage))",
        ).execute()
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            out[item["id"]] = {
                "default_audio_language": snippet.get("defaultAudioLanguage"),
                "default_language": snippet.get("defaultLanguage"),
            }
    return out


def _tracks(video_id: str) -> dict:
    """The raw caption-track facts from the player response."""
    api = youtube_service._build_transcript_api()
    captions = api._fetcher._fetch_captions_json(video_id)
    tracks = []
    for c in captions.get("captionTracks", []):
        tracks.append(
            {
                "language_code": c.get("languageCode"),
                "name": ((c.get("name") or {}).get("runs") or [{}])[0].get("text"),
                "kind": c.get("kind", "") or "manual",
                "vss_id": c.get("vssId"),
                "is_translatable": bool(c.get("isTranslatable", False)),
                "track_name": c.get("trackName"),
            }
        )
    audio_tracks = [
        {
            k: a.get(k)
            for k in (
                "captionTrackIndices",
                "defaultCaptionTrackIndex",
                "audioTrackId",
                "visibility",
                "hasDefaultTrack",
            )
            if k in a
        }
        for a in captions.get("audioTracks", [])
    ]
    return {
        "tracks": tracks,
        "audio_tracks": audio_tracks,
        "default_audio_track_index": captions.get("defaultAudioTrackIndex"),
        "translation_language_count": len(captions.get("translationLanguages", [])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-ids", default="", help="Comma-separated video ids")
    parser.add_argument("--job-prefixes", default="", help="Comma-separated job id prefixes")
    parser.add_argument(
        "--non-english-library", action="store_true",
        help="Also include every library video stored in a non-English language",
    )
    parser.add_argument("--out", required=True, help="Where to write the JSON findings")
    parser.add_argument(
        "--min-interval", type=float, default=4.0,
        help="Seconds between listings; never below YOUTUBE_TRANSCRIPT_RATE_LIMIT",
    )
    args = parser.parse_args(argv)

    videos = _collect_video_ids(
        [p for p in args.job_prefixes.split(",") if p], args.non_english_library
    )
    known = {v["video_id"] for v in videos}
    for vid in [v for v in args.video_ids.split(",") if v]:
        if vid not in known:
            videos.append({"video_id": vid, "stored_language": None, "title": None})
    print(f"{len(videos)} videos to measure")

    langs = _audio_languages([v["video_id"] for v in videos])
    print(f"videos.list returned audio languages for {len(langs)} videos (1 unit per 50 ids)")

    interval = max(float(settings.YOUTUBE_TRANSCRIPT_RATE_LIMIT), args.min_interval)
    results = []
    stopped = None
    last = 0.0
    for n, v in enumerate(videos, start=1):
        wait = interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        last = time.monotonic()
        row = dict(v)
        row.update(langs.get(v["video_id"], {"default_audio_language": None, "default_language": None}))
        try:
            row.update(_tracks(v["video_id"]))
        except Exception as exc:  # noqa: BLE001 — recorded, not raised
            row["error"] = f"{type(exc).__name__}"
            if youtube_service._is_ip_block_signal(exc):
                stopped = f"IP-block signal at video {n}: {type(exc).__name__}"
                results.append(row)
                print(stopped)
                break
        codes = [f"{t['language_code']}({'auto' if t['kind'] == 'asr' else 'manual'})" for t in row.get("tracks", [])]
        print(
            f"[{n}/{len(videos)}] {v['video_id']} audio={row.get('default_audio_language')} "
            f"stored={v['stored_language']} tracks={codes or row.get('error')}"
        )
        results.append(row)

    payload = {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "interval_seconds": interval,
        "stopped": stopped,
        "videos": results,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
