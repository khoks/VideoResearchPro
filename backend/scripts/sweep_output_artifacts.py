"""Find (and optionally delete) Author Studio artifact directories with no row (S-6.7.2).

Deleting an output removes its directory, best effort. A directory can still
be orphaned: a file locked at delete time on Windows, a crash between the
row delete and the file delete, or rows removed by hand. This lists every
``<OUTPUTS_DIR>/<user>/<output>/`` whose output row no longer exists, or
exists under a different owner.

    cd backend
    ./venv/Scripts/python scripts/sweep_output_artifacts.py            # dry run
    ./venv/Scripts/python scripts/sweep_output_artifacts.py --apply    # delete

Reads ``DATABASE_URL`` and ``OUTPUTS_DIR`` from the usual settings.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.services import output_artifacts  # noqa: E402


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="delete the orphaned directories (default: list only)")
    args = ap.parse_args(argv)

    db = SessionLocal()
    try:
        orphans = output_artifacts.find_orphans(db)
    finally:
        db.close()

    root = output_artifacts.outputs_root()
    if not orphans:
        print(f"No orphaned artifact directories under {root}.")
        return 0
    total = 0
    for path in orphans:
        size = _size(path)
        total += size
        print(f"{'deleting' if args.apply else 'orphan'}: {path.relative_to(root).as_posix()} ({size:,} bytes)")
        if args.apply:
            shutil.rmtree(path, ignore_errors=True)
    print(f"{len(orphans)} director{'y' if len(orphans) == 1 else 'ies'}, {total:,} bytes"
          + ("" if args.apply else " (dry run; pass --apply to delete)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
