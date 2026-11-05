"""Stamp the document-level ``code_mix_*`` fields onto older Chroma chunks (T-1.16.2.14).

Chunks written before S-1.16.2 (2026-10-19) carry no language fields, so the
prompts cannot tell a Hindi source from an English one when they retrieve
them. This script brings every chunk of a document with a stored
``documents.language_mix`` up to the fields ``chunk_transcript`` writes today:

    code_mix_primary, code_mix_script, code_mix_share,
    code_mix_matrix_share, code_mix_quote, code_mix_named_share

It reads the stored profile and computes nothing, so run
``scripts/backfill_language_mix.py --write`` first: a document with no profile
is counted and left alone. A chunk holding a different value is updated, which
is how a refreshed profile reaches its chunks. Plain-English documents carry no
fields. The per-chunk ``code_mix_chunk_share`` and ``code_mix_chunk_matrix`` are
not document-level and stay as they are.

**Those chunks stay embedded as their original text.** The English rendering
(D-084) needs the LLM and a re-embed, and this script does neither. It tells
every later prompt what language a chunk is in; it does not change what a
question retrieves, and the report says how many chunks that applies to.

A job that reuses a document already adds these fields to its chunks that lack
them (T-1.16.2.16). This script is still how every other document is reached,
and the only thing that rewrites a chunk holding a different value.

Nothing is re-embedded: the update is metadata only, each batch's stored
metadata is re-read and sent back whole with the new fields, and no LLM runs.
Dry run is the default and writes nothing. ``--write`` is the owner's step.
Idempotent (a second run finds nothing to change) and resumable (a pass stopped
by a failed batch is finished by running it again). Run it when no job is
ingesting: the worker writes the same collection.

A chunk of a document now profiled as plain English keeps the ``code_mix_*``
fields it was written with, and every prompt that retrieves it goes on saying
so: no normal path re-chunks an embedded document, so those fields never leave
on their own. ``--clear-stale`` with ``--write`` removes them, ``code_mix_chunk_*``
included. It is opt-in because it is the only thing here that removes data.

Usage (from backend/):
    ./venv/Scripts/python scripts/backfill_chunk_language_fields.py
    ./venv/Scripts/python scripts/backfill_chunk_language_fields.py --document-ids <id>,<id>
    ./venv/Scripts/python scripts/backfill_chunk_language_fields.py --json out.json
    ./venv/Scripts/python scripts/backfill_chunk_language_fields.py --write   # owner step
    ./venv/Scripts/python scripts/backfill_chunk_language_fields.py --write --clear-stale
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
from app.services.metadata_backfill_service import LANGUAGE_FIELDS  # noqa: E402


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="update the chunks (owner step)")
    parser.add_argument(
        "--clear-stale", action="store_true",
        help="with --write, remove code_mix_* from chunks of documents now plain English",
    )
    parser.add_argument("--document-ids", default="", help="comma-separated document ids")
    parser.add_argument("--page-size", type=int, default=1000, help="chunks per read and update")
    parser.add_argument("--json", dest="json_path", default=None, help="write the report here")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    document_ids = [d.strip() for d in args.document_ids.split(",") if d.strip()]
    mode = "WRITE" if args.write else "dry run (nothing is written)"
    print(f"backfill_chunk_language_fields — {mode}")

    db = SessionLocal()
    try:
        report = metadata_backfill_service.backfill_chunk_language_fields(
            db,
            write=args.write,
            page_size=max(1, args.page_size),
            document_ids=document_ids or None,
            clear_stale=args.clear_stale,
        )
    finally:
        db.close()

    data = report.as_dict()
    print(
        f"{data['documents_profiled']} document(s) with a stored profile, "
        f"{data['documents_code_mixed']} of them not plain English; "
        f"{data['chunks_scanned']} chunk(s) scanned: {data['chunks_matched']} of those "
        f"documents, {data['chunks_plain_english']} plain English, "
        f"{data['chunks_unprofiled']} of unprofiled documents, "
        f"{data['chunks_unresolved']} of no document in scope."
    )
    print(
        f"{data['chunks_already_current']} already current; {data['chunks_to_update']} "
        f"to update; {data['chunks_updated']} updated."
    )
    print(f"{'field':<24}{'gained':>10}{'changed':>10}")
    for name in LANGUAGE_FIELDS:
        print(f"{name:<24}{data['gained'][name]:>10}{data['changed'][name]:>10}")
    print(
        f"{data['chunks_embedded_as_original']} of these chunks have no English rendering "
        f"and stay embedded as their original text (D-084): this pass labels them, it does "
        f"not re-embed them."
    )
    if data["chunks_unprofiled"]:
        print("Unprofiled documents are skipped: run backfill_language_mix.py --write first.")
    if data["chunks_cleared"]:
        print(f"{data['chunks_cleared']} stale chunk(s) cleared of code_mix_* fields.")
    elif data["chunks_stale"]:
        print(
            f"{data['chunks_stale']} chunk(s) of documents now profiled as plain English still "
            f"carry code_mix_* fields, and no normal path re-chunks them, so they never self-heal. "
            f"--write --clear-stale removes those fields."
        )
    if data["stopped"]:
        print(f"STOPPED: {data['stopped']}")
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"report written to {args.json_path}")
    return 1 if data["stopped"] else 0


if __name__ == "__main__":
    sys.exit(main())
