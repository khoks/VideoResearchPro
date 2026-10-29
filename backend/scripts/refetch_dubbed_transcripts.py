"""Find cached transcripts that came from a caption track NOT in the video's
spoken language (an auto-dub, or a translation), and optionally re-fetch
them with the S-1.11.11 rule — T-1.11.11.3.

Before S-1.11.11, ``_fetch_transcript_once`` took ``en`` / ``en-auto`` and
then the first listed track, so the library holds Bengali dubs of Hindi
lectures (``1v3_AQ26jZ0``, ``5AuuOZ4vuxI``) and an English dub of a Hindi
interview (``v6CuYULP3tM``) — see docs/notes/2026-10-25-caption-track-choice.md.

What the script does, per cached YouTube transcript:

1. Skips Whisper transcripts (``source='whisper'``, or the Whisper-era
   language NAMES such as ``english`` on pre-provenance rows): Whisper hears
   the original audio, so it cannot have taken a dub.
2. Skips documents already fetched with the spoken-language rule (they carry
   ``source_metadata_json.caption_track``), unless ``--include-checked``.
3. Reads ``defaultAudioLanguage`` for the rest (Data API ``videos.list``,
   1 quota unit per 50 ids).
4. Lists the caption tracks of EVERY remaining row (free, paced at
   ``YOUTUBE_TRANSCRIPT_RATE_LIMIT`` or slower per D-051, stopping at the
   first IP-block signal). A cached transcript in the declared language is
   not proof it is no dub: 4 of 37 measured Hindi videos declare English,
   and an ``en-US`` dub cached under an ``en-IN`` declaration shares its
   primary subtag. About 4 s a row.
5. Reports each row whose spoken-language track is in a different language
   from the cached one: those are the re-fetches. Rows whose every track is
   a dub are reported separately as an owner decision (Whisper, which costs
   money, or leave them): no caption track can replace them.

Dry run is the default and writes NOTHING: the Data API call is issued
directly so not even the quota log gets a row. ``--write`` is the owner's
step; for each reported row it fetches the chosen track, deletes the old
chunks, writes ``transcript_cache`` and the document (language, word count,
caption track) in one transaction, then inserts the new chunks in the global
Chroma collection (``_refetch_one`` documents what a failure at each step
leaves). It stops at the first IP-block signal, as the dry run does.
Re-embedding a non-English chunk runs ``code_mixing_render_english`` (an LLM
call) when ``CODE_MIX_ENGLISH_RENDERING_ENABLED`` is on. Knowledge reports
built from the dub are listed, not regenerated.

Usage (from backend/):
    ./venv/Scripts/python scripts/refetch_dubbed_transcripts.py
    ./venv/Scripts/python scripts/refetch_dubbed_transcripts.py --video-ids 1v3_AQ26jZ0,v6CuYULP3tM
    ./venv/Scripts/python scripts/refetch_dubbed_transcripts.py --json out.json
    ./venv/Scripts/python scripts/refetch_dubbed_transcripts.py --write   # owner step
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.transcript_cache import TranscriptCache  # noqa: E402
from app.services import youtube_service  # noqa: E402
from app.services.youtube_service import primary_language  # noqa: E402

# A BCP-47-ish code ("hi", "en-US", "zh-Hans", "es-419"). Anything else —
# "english", "welsh" — is a language NAME, which only Whisper ever wrote.
_CODE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

# Statuses printed per row (the rest only appear in the counts).
_REPORTED = (
    "refetch", "refetched", "refetched_unembedded", "refetch_failed", "list_failed",
)


@dataclass
class Row:
    video_id: str
    document_id: str
    title: str
    cached_language: str
    cached_source: str
    has_knowledge: bool
    declared_audio_language: str | None = None
    status: str = ""  # see decide() and run()
    chosen_language: str | None = None
    chosen_kind: str | None = None
    spoken_language: str | None = None
    spoken_language_source: str | None = None
    match: str | None = None
    available: list[str] = field(default_factory=list)
    skipped_dubbed: list[str] = field(default_factory=list)
    note: str = ""


def _is_whisper(cached_language: str, cached_source: str | None) -> bool:
    return (cached_source or "") == "whisper" or not _CODE_RE.match(cached_language or "")


def load_candidates(db, video_ids: list[str] | None, include_checked: bool) -> tuple[list[Row], dict]:
    """Cached YouTube transcripts that could have come from a dub."""
    q = (
        db.query(TranscriptCache, Document)
        .join(Document, Document.document_id == TranscriptCache.document_id)
        .filter(Document.source_type == "video", Document.video_id.isnot(None))
    )
    if video_ids:
        q = q.filter(Document.video_id.in_(video_ids))
    rows: list[Row] = []
    skipped = {"whisper": 0, "already_checked": 0}
    for cache, doc in q.order_by(Document.video_id):
        if _is_whisper(cache.language, cache.source):
            skipped["whisper"] += 1
            continue
        if not include_checked and _caption_track(doc):
            skipped["already_checked"] += 1
            continue
        rows.append(
            Row(
                video_id=doc.video_id,
                document_id=doc.document_id,
                title=(doc.title or "")[:80],
                cached_language=cache.language,
                cached_source=cache.source or "youtube",
                has_knowledge=bool(doc.extracted_knowledge_json or doc.knowledge_report_md),
            )
        )
    return rows, skipped


def _caption_track(doc: Document) -> dict | None:
    try:
        meta = json.loads(doc.source_metadata_json) if doc.source_metadata_json else {}
    except (TypeError, ValueError):
        return None
    track = meta.get("caption_track") if isinstance(meta, dict) else None
    return track if isinstance(track, dict) else None


def declared_audio_languages(video_ids: list[str], record_quota: bool) -> dict[str, str | None]:
    """``defaultAudioLanguage`` per id. The dry run issues the request
    directly so nothing (not even the quota log) is written."""
    if record_quota:
        return youtube_service.get_default_audio_languages(video_ids)
    youtube = youtube_service.get_youtube_client()
    out: dict[str, str | None] = {vid: None for vid in video_ids}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        response = youtube.videos().list(
            part="snippet", id=",".join(batch),
            fields="items(id,snippet(defaultAudioLanguage))",
        ).execute()
        for item in response.get("items", []):
            out[item["id"]] = (item.get("snippet") or {}).get("defaultAudioLanguage") or None
    return out


def decide(row: Row, choice) -> str:
    """``refetch`` when the spoken-language track's language differs from the
    cached transcript's; otherwise why not."""
    row.chosen_language = choice.language
    row.chosen_kind = choice.kind
    row.spoken_language = choice.spoken_language
    row.spoken_language_source = choice.spoken_language_source
    row.match = choice.match
    row.available = list(choice.available)
    row.skipped_dubbed = list(choice.skipped_dubbed)
    if choice.track is None:
        return "no_spoken_track" if choice.match == "only_dubbed" else "no_tracks"
    if primary_language(choice.language) != primary_language(row.cached_language):
        return "refetch"
    return "ok"


def _write_cache_row(db, doc: Document, segments: list[dict], language: str) -> None:
    """Upsert the transcript cache row in the CALLER's session, so it commits
    with the document (``youtube_service._save_to_cache`` commits through its
    own session and swallows failures)."""
    payload = json.dumps(segments)
    cache = (
        db.query(TranscriptCache)
        .filter(TranscriptCache.document_id == doc.document_id)
        .one_or_none()
    )
    if cache is None:
        db.add(
            TranscriptCache(
                document_id=doc.document_id,
                video_id=doc.video_id,
                segments_json=payload,
                language=language,
                source="youtube",
            )
        )
    else:
        cache.segments_json = payload
        cache.language = language
        cache.source = "youtube"
        cache.fetched_at = datetime.now(timezone.utc)


def _refetch_one(db, row: Row, choice) -> tuple[str, str]:
    """Owner step: replace one document's transcript, cache row and chunks.

    Returns ``(status, note)``. The order is chosen so a failure at any step
    leaves a state that the next run detects or the next job repairs:

    1. Fetch the chosen track and chunk it. Nothing is written yet. An
       IP-block raised by the fetch propagates, and ``run`` stops.
    2. Delete the old chunks. ``delete_video_chunks`` reports failure by
       returning False; then nothing is written, the cache still holds the
       dub, and the next run lists the row again. (An upsert over a
       failed delete would leave every dub chunk past the new count.)
    3. Write the cache row and the document in ONE transaction, the
       document marked un-embedded. A new cache never sits beside a
       document that still describes the dub. If this fails, the document is
       marked un-embedded (its chunks are gone) and the error propagates;
       the cache still holds the dub, so the next run lists it again.
    4. Insert the new chunks and mark the document embedded. If the insert
       fails the document stays un-embedded, and the next job that selects
       it embeds the new text from the cache (its old chunks are gone).
    """
    from app.services import chroma_service
    from app.tasks.job_tasks import _build_video_metadata
    from app.utils.chunking import chunk_transcript

    transcript = choice.track.fetch()
    segments = youtube_service._transcript_to_list(transcript)
    if not segments:
        return "refetch_failed", "fetched an empty transcript; nothing written"
    language = getattr(transcript, "language_code", None) or choice.language
    doc = db.query(Document).filter(Document.document_id == row.document_id).one()
    chunks = chunk_transcript(
        segments,
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        video_metadata=_build_video_metadata(doc, language),
    )

    if not chroma_service.delete_video_chunks(row.video_id):
        return (
            "refetch_failed",
            "could not delete the old chunks; nothing written (the dub is still "
            "cached, so the next run lists this row again)",
        )

    try:
        _write_cache_row(db, doc, segments, language)
        doc.transcript_language = language
        doc.transcript_word_count = sum(len(s.get("text", "").split()) for s in segments)
        doc.transcripted_at = datetime.now(timezone.utc)
        doc.transcript_source = "youtube"
        doc.embedded_in_chroma = False
        try:
            meta = json.loads(doc.source_metadata_json) if doc.source_metadata_json else {}
        except (TypeError, ValueError):
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        meta["caption_track"] = choice.as_metadata()
        doc.source_metadata_json = json.dumps(meta)
        db.commit()
    except Exception:
        db.rollback()
        # The old chunks are gone: say so, so a job re-embeds from the cache.
        db.query(Document).filter(Document.document_id == row.document_id).update(
            {Document.embedded_in_chroma: False}
        )
        db.commit()
        raise

    try:
        chroma_service.insert_chunks(chunks)
    except Exception as exc:  # noqa: BLE001 — the cache already holds the new text
        return (
            "refetched_unembedded",
            f"re-fetched in {language}, but embedding failed ({type(exc).__name__}); "
            "marked un-embedded, the next job that selects it embeds it from cache",
        )
    doc.embedded_in_chroma = True
    db.commit()
    return (
        "refetched",
        f"re-fetched in {language}: {doc.transcript_word_count} words -> {len(chunks)} chunks",
    )


def run(
    db,
    *,
    video_ids: list[str] | None = None,
    include_checked: bool = False,
    write: bool = False,
    min_interval: float = 4.0,
    limit: int = 0,
    ytt_api=None,
    sleep=time.sleep,
) -> dict:
    """The whole pass; returns the report. Importable for tests."""
    rows, skipped = load_candidates(db, video_ids, include_checked)
    if limit > 0:
        rows = rows[:limit]
    declared = declared_audio_languages([r.video_id for r in rows], record_quota=write) if rows else {}
    for r in rows:
        r.declared_audio_language = declared.get(r.video_id)

    interval = max(float(settings.YOUTUBE_TRANSCRIPT_RATE_LIMIT), min_interval)
    ytt_api = ytt_api or youtube_service._build_transcript_api()
    stopped = None
    last = None
    listed = 0
    for n, r in enumerate(rows, start=1):
        if last is not None:
            wait = interval - (time.monotonic() - last)
            if wait > 0:
                sleep(wait)
        last = time.monotonic()
        listed += 1
        try:
            choice = youtube_service.plan_caption_track(
                ytt_api, r.video_id,
                language=settings.DEFAULT_TRANSCRIPT_LANGUAGE,
                audio_language=r.declared_audio_language,
            )
        except Exception as exc:  # noqa: BLE001 — recorded per row
            r.status = "list_failed"
            r.note = type(exc).__name__
            if youtube_service._is_ip_block_signal(exc):
                stopped = f"IP-block signal at row {n} ({type(exc).__name__}); stopped"
                break
            continue
        r.status = decide(r, choice)
        if write and r.status == "refetch":
            try:
                r.status, r.note = _refetch_one(db, r, choice)
            except Exception as exc:  # noqa: BLE001 — one failure must not stop the pass
                db.rollback()
                r.status = "refetch_failed"
                r.note = f"{type(exc).__name__}: {exc}"
                if youtube_service._is_ip_block_signal(exc):
                    stopped = f"IP-block signal while re-fetching row {n} ({type(exc).__name__}); stopped"
                    break

    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status or "not_reached"] = counts.get(r.status or "not_reached", 0) + 1
    return {
        "mode": "write" if write else "dry_run",
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "skipped": skipped,
        "candidates": len(rows),
        "listed": listed,
        "interval_seconds": interval,
        "stopped": stopped,
        "counts": counts,
        # Every caption track is a dub: no track can replace the cached text,
        # and --write leaves it. The owner decides (Whisper costs money).
        "owner_decisions": [
            {"video_id": r.video_id, "document_id": r.document_id,
             "cached_language": r.cached_language, "skipped_dubbed": r.skipped_dubbed,
             "title": r.title}
            for r in rows if r.status == "no_spoken_track"
        ],
        "rows": [asdict(r) for r in rows],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video-ids", default="", help="Comma-separated subset (default: the whole library)")
    parser.add_argument("--include-checked", action="store_true",
                        help="Also re-check documents already fetched with the spoken-language rule")
    parser.add_argument("--limit", type=int, default=0, help="Max candidates (0 = all)")
    parser.add_argument("--min-interval", type=float, default=4.0,
                        help="Seconds between listings; never below YOUTUBE_TRANSCRIPT_RATE_LIMIT")
    parser.add_argument("--json", default="", help="Also write the report to this path")
    parser.add_argument("--write", action="store_true",
                        help="OWNER STEP: re-fetch, overwrite the cache and replace the chunks")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        report = run(
            db,
            video_ids=[v for v in args.video_ids.split(",") if v] or None,
            include_checked=args.include_checked,
            write=args.write,
            min_interval=args.min_interval,
            limit=args.limit,
        )
    finally:
        db.close()

    print(f"Mode: {report['mode']}")
    print(f"Skipped: {report['skipped']['whisper']} Whisper, "
          f"{report['skipped']['already_checked']} already fetched with the spoken-language rule")
    print(f"Candidates: {report['candidates']}, tracks listed for {report['listed']}")
    if report["stopped"]:
        print(report["stopped"])
    for r in report["rows"]:
        if r["status"] in _REPORTED:
            print(
                f"  {r['status']:<20} {r['video_id']}  cached={r['cached_language']} -> "
                f"{r['chosen_language']} ({r['chosen_kind']}, spoken={r['spoken_language']} via "
                f"{r['spoken_language_source']})"
                f"{' [knowledge report built from the old text]' if r['has_knowledge'] else ''}"
                f"{'  ' + r['note'] if r['note'] else ''}  {r['title'][:50]}"
            )
    if report["owner_decisions"]:
        print(
            f"Owner decision: {len(report['owner_decisions'])} cached transcript(s) came from a "
            "dub and the video has no caption track in its spoken language. --write leaves them; "
            "re-transcribe with Whisper (paid) or remove them:"
        )
        for d in report["owner_decisions"]:
            print(f"  {d['video_id']}  cached={d['cached_language']} dubs={d['skipped_dubbed']}  {d['title'][:50]}")
    print(f"Counts: {report['counts']}")
    if not args.write and report["counts"].get("refetch"):
        print("Dry run: nothing written. Re-run with --write to re-fetch (owner step).")
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Report written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
