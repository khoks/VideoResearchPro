"""Find documents flagged embedded with no chunk in the library (T-5.2.24).

Runs before PR #440 (D-161) could leave a document flagged
``embedded_in_chroma`` with no chunk in Chroma: a run stopped between
extraction and the RAG build (a cancel, a route failing the row, an
exception), or, before D-070 (2026-10-19), any source without a ``video_id``.
Every later job reuses such a document as embedded and inserts nothing, so no
job or library Q&A retrieves it.

This reads the database and the global collection's metadata, and reports by
source type how many flagged documents no chunk names, by ``document_id``
metadata or, for chunks written before 2026-10-19, by chunk id
(``{video_id}:{index}`` for YouTube, ``{document_id}:{index}`` otherwise). It
sorts them by where their text lives:

* cached: ``transcript_cache`` holds it. Unflagged, the next job that selects
  one re-chunks it from there and inserts it, with no fetch.
* fetch again: their text lived only in the chunks that never got written, so
  only a fresh fetch brings it back. A job that selects one already does that;
  a PDF is selected by no job, a pasted page only when a search finds it.
* empty: cached text with no words. Nothing to embed; left flagged.

It prints ids and counts, never text, and loads no embedding model, makes no
LLM call and no network request. Dry run is the default: it cannot write (on
SQLite the session runs with ``PRAGMA query_only``). ``--write`` is the
owner's step: it clears the flag on the cached and fetch-again documents,
each re-checked against Chroma just before, and changes nothing in Chroma. A
scan that stops part-way, or a store none of whose chunks belongs to this
database, writes nothing. Idempotent: a second run finds nothing to clear.
Run it when no job is ingesting.

Usage (from backend/):
    ./venv/Scripts/python scripts/check_embedded_flags.py
    ./venv/Scripts/python scripts/check_embedded_flags.py --document-ids <id>,<id>
    ./venv/Scripts/python scripts/check_embedded_flags.py --json out.json
    ./venv/Scripts/python scripts/check_embedded_flags.py --write   # owner step
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.services import embedded_flag_service  # noqa: E402
from app.services.embedded_flag_service import (  # noqa: E402
    BUCKET_CACHED,
    BUCKET_EMPTY,
    BUCKET_FETCH_AGAIN,
    BUCKETS,
)

_LABELS = {
    BUCKET_CACHED: "text in transcript_cache: the next job that selects one embeds it from there",
    BUCKET_FETCH_AGAIN: "text nowhere else: only a fresh fetch brings it back",
    BUCKET_EMPTY: "cached text with no words: nothing to embed, left flagged",
}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="clear the flags found (owner step)")
    parser.add_argument("--document-ids", default="", help="comma-separated document ids")
    parser.add_argument("--page-size", type=int, default=1000, help="chunks per metadata read")
    parser.add_argument("--json", dest="json_path", default=None, help="write the report here")
    return parser.parse_args(argv)


def _query_only(db, on: bool) -> None:
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text(f"PRAGMA query_only = {'ON' if on else 'OFF'}"))


def _print(data: dict) -> None:
    print(
        f"{data['collection']}: {data['chunks_scanned']} chunk(s) scanned, "
        f"{data['chunks_of_no_document']} of no document in this database."
    )
    print(
        f"{data['flagged']} document(s) flagged embedded: {data['flagged_with_chunks']} with "
        f"chunks, {data['without_chunks']} without. {data['unflagged_with_chunks']} not "
        "flagged have chunks (left alone)."
    )
    header = f"{'source type':<14}{'flagged':>9}{'chunks':>8}" + "".join(f"{b:>13}" for b in BUCKETS)
    print(header)
    for source_type, counts in data["by_source"].items():
        print(
            f"{source_type:<14}{counts.get('flagged', 0):>9}{counts.get('with_chunks', 0):>8}"
            + "".join(f"{counts.get(b, 0):>13}" for b in BUCKETS)
        )
    for bucket in BUCKETS:
        rows = data["found"][bucket]
        print(f"{bucket} ({_LABELS[bucket]}): {len(rows)}")
        for row in rows:
            print(f"  {row['document_id']}  {row['source_type']:<10} {row['video_id'] or '-'}")
    verb = "cleared" if data["write"] else "would clear"
    print(f"{verb} {data['cleared'] if data['write'] else data['to_clear']} flag(s)"
          + (f"; {data['kept_on_recheck']} kept, embedded since the scan" if data["write"] else ""))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    document_ids = [d.strip() for d in args.document_ids.split(",") if d.strip()]
    print(f"check_embedded_flags — {'WRITE' if args.write else 'dry run (nothing is written)'}")

    db = SessionLocal()
    db.get_bind().echo = False  # DEBUG would print every bound value
    try:
        if not args.write:
            _query_only(db, True)
        report = embedded_flag_service.check_embedded_flags(
            db,
            write=args.write,
            page_size=max(1, args.page_size),
            document_ids=document_ids or None,
        )
    finally:
        if not args.write:
            _query_only(db, False)
        db.close()

    data = report.as_dict()
    _print(data)
    if data["stopped"]:
        print(f"STOPPED: {data['stopped']}")
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"report written to {args.json_path}")
    return 1 if data["stopped"] else 0


if __name__ == "__main__":
    sys.exit(main())
