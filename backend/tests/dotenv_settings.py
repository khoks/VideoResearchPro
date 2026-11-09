"""The real ``Settings`` as a subprocess would load it (T-4.11.4.3).

A test that starts the app in a subprocess from backend/ hands it an
environment of its own, and ``Settings`` there also reads ``backend/.env``,
which in the main checkout is the install's own. A variable the environment
holds beats the file, an empty one included; one it lacks lets the file's
value in. CI and a worktree have no ``.env``, so such a leak shows only on the
owner's machine. This loads ``Settings`` under the environment a helper built,
with a ``.env`` the test writes, and never reads the real one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


def settings_loaded_as(
    env: dict[str, str], dotenv: dict[str, str], *, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> Settings:
    """``Settings`` as a process started with ``env`` loads it from a directory
    whose ``.env`` holds ``dotenv``. Only the names in ``dotenv`` are put in
    step with ``env``: no other name can come from the file."""
    path = folder / "install.env"
    path.write_text("".join(f"{name}={value}\n" for name, value in dotenv.items()), encoding="utf-8")
    for name in dotenv:
        if name in env:
            monkeypatch.setenv(name, env[name])
        else:
            monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=path, _env_file_encoding="utf-8")
