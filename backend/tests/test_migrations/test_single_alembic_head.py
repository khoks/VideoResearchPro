"""The migration chain has one head.

Two branches can each add a migration on the same parent and merge with no file
conflict, so the merge looks clean and `alembic upgrade head` then stops with
"Multiple head revisions" on the owner's next start. A failure here means
re-parenting the newer migration onto the other, not adding a merge revision.
"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND = Path(__file__).resolve().parents[2]


def test_the_migration_chain_has_one_head() -> None:
    cfg = Config(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"re-parent the newer of these migrations: {sorted(heads)}"
