"""Backfill the era and numeric publish fields into older Chroma chunks (S-1.17.3).

Chunks embedded before R3 shipped (2026-10-19) carry no ``era_*`` and no
``published_ts`` / ``published_year`` metadata, and a document whose era was
extracted after its chunks were embedded (a job that reused it) has the era
on the document but not on its chunks. Both read as "unknown" at retrieval.
This script brings every chunk of a document with ``discussed_era_json`` or
``published_at`` up to the fields ``chunk_transcript`` writes today:

    era_start, era_end, era_confidence, is_retrospective,
    published_ts, published_year

Unknown fields are left out, never written as sentinels (an era with no
start year or zero confidence counts as unknown, as at chunk time). Nothing
is removed and nothing is re-embedded: the update is metadata only, and each
batch's stored metadata is re-read and sent back whole with the new fields,
so ``document_id``, ``code_mix_*``, ``text_en``, timestamps and every other
key survive. It needs no LLM.

Dry run is the default and writes nothing; it reports, per field, how many
chunks would gain it and how many hold a different value. ``--write`` is the
owner's step. Idempotent (a second run finds nothing to change) and
resumable (a pass stopped by a failed batch is finished by running it again).
Run it when no job is ingesting: the worker writes the same collection.

Usage (from backend/):
    ./venv/Scripts/python scripts/backfill_chunk_temporal_fields.py
    ./venv/Scripts/python scripts/backfill_chunk_temporal_fields.py --document-ids <id>,<id>
    ./venv/Scripts/python scripts/backfill_chunk_temporal_fields.py --json out.json
    ./venv/Scripts/python scripts/backfill_chunk_temporal_fields.py --write   # owner step
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.services import metadata_backfill_service  # noqa: E402
from app.services.metadata_backfill_service import TEMPORAL_FIELDS  # noqa: E402


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="update the chunks (owner step)")
    parser.add_argument("--document-ids", default="", help="comma-separated document ids")
    parser.add_argument("--page-size", type=int, default=1000, help="chunks per read and update")
    parser.add_argument("--json", dest="json_path", default=None, help="write the report here")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    document_ids = [d.strip() for d in args.document_ids.split(",") if d.strip()]
    mode = "WRITE" if args.write else "dry run (nothing is written)"
    print(f"backfill_chunk_temporal_fields — {mode}")

    db = SessionLocal()
    try:
        report = metadata_backfill_service.backfill_chunk_temporal_fields(
            db,
            write=args.write,
            page_size=max(1, args.page_size),
            document_ids=document_ids or None,
        )
    finally:
        db.close()

    data = report.as_dict()
    print(
        f"{data['documents_with_dates']} document(s) with an era or a publish date; "
        f"{data['chunks_scanned']} chunk(s) scanned: {data['chunks_matched']} of dated "
        f"documents, {data['chunks_undated']} of undated ones, "
        f"{data['chunks_unresolved']} of no document in scope."
    )
    print(
        f"{data['chunks_already_current']} already current; {data['chunks_to_update']} "
        f"to update; {data['chunks_updated']} updated."
    )
    print(f"{'field':<18}{'gained':>10}{'changed':>10}")
    for name in TEMPORAL_FIELDS:
        print(f"{name:<18}{data['gained'][name]:>10}{data['changed'][name]:>10}")
    if data["stopped"]:
        print(f"STOPPED: {data['stopped']}")
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"report written to {args.json_path}")
    return 1 if data["stopped"] else 0


if __name__ == "__main__":
    sys.exit(main())
