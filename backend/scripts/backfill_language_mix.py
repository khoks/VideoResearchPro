"""Profile the language mix of documents chunked before T-1.16.1.7.

Every chunking path now stores ``code_mixing_service.profile_transcript``'s
result on ``documents.language_mix``. Documents chunked earlier have none.
This script computes it from the text the library already holds, with the
lexicon tagger and no LLM:

* ``transcript_cache`` (YouTube transcripts and cached connector text): the
  segments the chunker read, so the profile equals the one chunking computes;
* otherwise the document's chunks in the global Chroma collection,
  reassembled the way knowledge reports read them (PR #383): stale tail
  dropped, ``chunk_index`` order, overlap removed, visual annotations
  stripped. PDFs and pasted pages keep their text nowhere else.

Only documents with text are read (``transcript_status='fetched'`` or
embedded), and by default only those with no profile yet. Dry run is the
default and writes nothing. ``--write`` (the owner's step) stores each
profile and commits it at once, so an interrupted run is finished by running
it again. Chroma is only read.

A tagger change does not reach a stored profile by itself. ``--all --write``
re-profiles every document and rewrites only the profiles that differ; then
``scripts/backfill_chunk_language_fields.py --write`` carries them to the chunks.

Usage (from backend/):
    ./venv/Scripts/python scripts/backfill_language_mix.py
    ./venv/Scripts/python scripts/backfill_language_mix.py --document-ids <id>,<id>
    ./venv/Scripts/python scripts/backfill_language_mix.py --all --json out.json
    ./venv/Scripts/python scripts/backfill_language_mix.py --write   # owner step
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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="store the profiles (owner step)")
    parser.add_argument(
        "--all", dest="recompute", action="store_true",
        help="also re-profile documents that already have one (written only where it differs)",
    )
    parser.add_argument("--document-ids", default="", help="comma-separated document ids")
    parser.add_argument("--limit", type=int, default=None, help="at most this many documents")
    parser.add_argument("--json", dest="json_path", default=None, help="write the report here")
    parser.add_argument("--quiet", action="store_true", help="no per-document lines")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    document_ids = [d.strip() for d in args.document_ids.split(",") if d.strip()]

    def on_row(document, outcome: str, profile: dict | None) -> None:
        if args.quiet or outcome == "unchanged":
            return
        title = (document.title or "")[:60]
        if profile is None:
            print(f"  {outcome:<9} {document.document_id}  '{title}'")
            return
        print(
            f"  {outcome:<9} {document.document_id}  {profile.get('primary_language'):<5} "
            f"{(profile.get('native_script') or '-'):<10} "
            f"non-English {profile.get('hi_share', 0):.1%}  '{title}'"
        )

    mode = "WRITE" if args.write else "dry run (nothing is written)"
    print(f"backfill_language_mix — {mode}")
    db = SessionLocal()
    try:
        report = metadata_backfill_service.backfill_language_mix(
            db,
            write=args.write,
            recompute=args.recompute,
            document_ids=document_ids or None,
            limit=args.limit,
            on_row=on_row,
        )
    finally:
        db.close()

    data = report.as_dict()
    verb = "stored" if args.write else "would store"
    print()
    print(
        f"{data['considered']} document(s) considered: {data['profiled']} profiled "
        f"({', '.join(f'{k} {v}' for k, v in sorted(data['by_origin'].items())) or 'none'}), "
        f"{data['no_text']} with no stored text, {data['failed']} failed."
    )
    print(
        f"{verb} {data['changed']} profile(s); {data['unchanged']} already current. "
        f"Primary language: "
        f"{', '.join(f'{k} {v}' for k, v in sorted(data['by_primary'].items())) or 'none'}; "
        f"{data['code_mixed']} not plain English (their chunks carry code_mix_*)."
    )
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"report written to {args.json_path}")
    return 1 if data["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
