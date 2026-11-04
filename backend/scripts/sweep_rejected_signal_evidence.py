"""Sweep stale evidence out of rejected voice signals (T-3.3.1.7).

A signal rejected before PR #392 can still hold the words of a source deleted
while it was rejected: the old withdrawal skipped rejected rows, and the delete
paths drop the ledger row at once, so no later run cleans them. Restore,
the Rejected list and the brain export already keep those words from showing;
this clears them from the row. Every rejection stays a rejection.

Dry run is the default and cannot write: on SQLite it runs with
``PRAGMA query_only``. ``--write`` (the owner's step) applies it, tenant by
tenant, so an interrupted run is finished by running it again; a second run
changes nothing. It prints counts, never the words.

Usage (from backend/):
    ./venv/Scripts/python scripts/sweep_rejected_signal_evidence.py
    ./venv/Scripts/python scripts/sweep_rejected_signal_evidence.py --tenant <id>
    ./venv/Scripts/python scripts/sweep_rejected_signal_evidence.py --write   # owner step
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models.voice_signal import VoiceSignal  # noqa: E402
from app.services import echo_signal_service  # noqa: E402


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="apply the sweep (owner step)")
    parser.add_argument("--tenant", default=None, help="only this tenant id")
    return parser.parse_args(argv)


def _query_only(db, on: bool) -> None:
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text(f"PRAGMA query_only = {'ON' if on else 'OFF'}"))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    print(f"sweep_rejected_signal_evidence — {'WRITE' if args.write else 'dry run (nothing is written)'}")
    db = SessionLocal()
    db.get_bind().echo = False  # DEBUG would print each row's words as parameters
    try:
        if not args.write:
            _query_only(db, True)
        tenants = [args.tenant] if args.tenant else sorted(
            t for (t,) in db.query(VoiceSignal.tenant_id).filter(VoiceSignal.suppressed_reason == "user").distinct()
        )
        total = echo_signal_service.RejectedSweep()
        for tenant_id in tenants:
            found = echo_signal_service.sweep_rejected_evidence(db, tenant_id, write=args.write)
            total.add(found)
            if found.stale:
                print(f"  {tenant_id[:8]}  {found.stale} of {found.rejected} rejections: "
                      f"{found.examples} examples, {found.refs} refs")
        verb = "cleared" if args.write else "would clear"
        print(f"{len(tenants)} tenants with rejections, {total.rejected} rejections, {total.stale} stale: "
              f"{verb} {total.examples} examples and {total.refs} refs")
    finally:
        if not args.write:
            _query_only(db, False)
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
