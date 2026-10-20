"""Import an export file into a user's Echo from the command line (S-3.7.5).

For exports past the web upload's cap (``ECHO_IMPORT_MAX_BYTES``), above all
Apple Health's ``export.zip``, which runs to gigabytes. It is the same flow as
``POST /echo/import``: the same importers, options, preview and undo record.
Shares are embedded inline here unless ``--queue`` hands them to the worker.

    cd backend
    ./venv/Scripts/python scripts/echo_import.py --email you@example.com --file ~/Downloads/export.zip --preview
    ./venv/Scripts/python scripts/echo_import.py --email you@example.com --file ~/Downloads/export.zip
    ./venv/Scripts/python scripts/echo_import.py --email you@example.com --file chat.txt \\
        --options '{"self_name": "Rahul", "timezone": "Asia/Kolkata"}'
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None, *, session_factory=None) -> int:
    parser = argparse.ArgumentParser(description="Import an export file into Echo.")
    parser.add_argument("--email", required=True, help="The account to import into.")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--importer", default=None, help="Force an importer (default: detected).")
    parser.add_argument("--options", default="{}", help="Importer options as a JSON object.")
    parser.add_argument("--preview", action="store_true", help="Show what would be imported; write nothing.")
    parser.add_argument("--queue", action="store_true", help="Leave embedding to the Celery worker.")
    parser.add_argument("--max-unpacked-mb", type=int, default=None,
                        help="Raise the cap on what a zip may unpack to (default: ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES).")
    args = parser.parse_args(argv)

    from app.config import settings
    import app.models  # noqa: F401  (registers every model)
    from app.connectors.archive import ExportUnreadable
    from app.models.user import User
    from app.services import echo_import_service
    from app.services.tier_service import has_feature

    if session_factory is None:
        from app.database import SessionLocal as session_factory  # noqa: N813

    try:
        options = json.loads(args.options)
    except ValueError:
        parser.error("--options must be a JSON object")
    if not isinstance(options, dict):
        parser.error("--options must be a JSON object")
    if not args.file.is_file():
        parser.error(f"{args.file} is not a file")
    if args.max_unpacked_mb:
        settings.ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES = args.max_unpacked_mb * 1024 * 1024
    settings.ECHO_SHARE_PROCESSING = "celery" if args.queue else "inline"

    db = session_factory()
    try:
        user = db.query(User).filter(User.email == args.email.strip().lower()).one_or_none()
        if user is None:
            print(f"No account with the email {args.email}.", file=sys.stderr)
            return 2
        if not has_feature(user, "echo_personal_brain"):
            print("Echo needs the Studio plan on that account.", file=sys.stderr)
            return 2
        with open(args.file, "rb") as fh:
            try:
                if args.preview:
                    pv = echo_import_service.preview(fh, args.file.name, importer=args.importer, options=options)
                    print(json.dumps({
                        "importer": pv.importer, "label": pv.label, "summary": pv.summary,
                        "participants": pv.participants, "options": pv.options, "warnings": pv.warnings,
                    }, indent=2, ensure_ascii=False, default=str))
                    return 0
                record = echo_import_service.run_import(
                    db, user, fh, args.file.name, importer=args.importer, options=options,
                )
            except ExportUnreadable as e:
                print(f"Not imported: {e}", file=sys.stderr)
                return 1
        print(json.dumps({
            "import_id": record.id, "importer": record.importer, "status": record.status,
            "counts": json.loads(record.counts_json or "{}"),
        }, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
