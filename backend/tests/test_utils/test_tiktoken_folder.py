"""T-8.8.6.5 — the API and the worker keep tiktoken's encoding in
TIKTOKEN_ENCODINGS_DIR, not in the temp folder.

The first two tests are the production callers, each in a fresh interpreter
started the way that process starts: nothing in the environment names a
folder, the temp folder is empty, and every lookup fails as in a DNS drop. The
real encoding is only in the app's folder, so a count that comes back right
was read from there. The rest cover what ``use_app_folder`` decides, in this
process, with the suite's own choice set aside and put back after.

Mutation checks (each failed the named test when this shipped): dropping the
call from ``app/tasks/celery_app.py`` (``test_the_worker_counts_offline_from_the_folder``);
dropping it from both that file and ``app/main.py``
(``test_the_api_counts_offline_from_the_folder`` too; with only the one in
``main.py`` gone, the API still applies it through the worker's module, which
every router imports); overriding a variable that is already set
(``test_a_folder_the_environment_chose_is_left_alone``); dropping the write
probe (``test_a_folder_that_cannot_be_written_leaves_tiktokens_default``);
dropping the copy from the temp folder (``test_an_earlier_copy_needs_no_download``).
"""
from __future__ import annotations

import errno
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import tiktoken.load
import tiktoken.registry
import tiktoken_ext.openai_public

from app.agents import knowledge_agent, report_agent
from app.config import settings
from app.utils import chunking, tiktoken_cache
from tests import tiktoken_cache as suite_cache

_BACKEND = Path(__file__).resolve().parents[2]
# Read at collection, before any test could download the file or set the
# suite's folder aside.
CACHED_AT_START = suite_cache.encoding_is_cached()
_SUITE_COPY = Path(suite_cache.chosen() or Path(tempfile.gettempdir()) / "data-gym-cache") / suite_cache.cache_file()
FAKE = b"not the real encoding"
TEXT = "Echoes come back."
TOKENS = 5
_SECRET = ("_KEY", "_SECRET", "_TOKEN", "_PASSWORD")


def _real_encoding() -> Path:
    """The suite's cached copy of cl100k_base. On a machine a missing file is a
    first run; on a runner, CI's download step has just put it there."""
    if not CACHED_AT_START:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail("cl100k_base is not in the cache the run restored. Bump MODEL_CACHE_KEY in .github/workflows/ci.yml.")
        pytest.skip("first run here: the encoding was not cached at the start")
    return _SUITE_COPY


# ---------------------------------------------------------------------------
# The production callers
# ---------------------------------------------------------------------------

_OFFLINE = r"""
import importlib, os, socket, sys

asked = []

def refuse(*args, **kwargs):
    asked.append(args[:1])
    raise OSError("no network")

socket.getaddrinfo = refuse
socket.create_connection = refuse

importlib.import_module(sys.argv[1])
from app.utils import chunking

print(os.environ.get("TIKTOKEN_CACHE_DIR"))
print(chunking._count_tokens(sys.argv[2]))
print(len(asked))
"""


def _start_offline(tmp_path: Path, module: str) -> tuple[Path, list[str]]:
    """Import ``module`` as its process does, then count ``TEXT``. The working
    directory holds no ``.env``, and nothing secret is passed on."""
    folder = tmp_path / "encodings"
    folder.mkdir()
    shutil.copyfile(_real_encoding(), folder / tiktoken_cache.cache_file())
    temp = tmp_path / "temp"
    temp.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in ("TIKTOKEN_CACHE_DIR", "DATA_GYM_CACHE_DIR") and not name.endswith(_SECRET)
    }
    env.update(
        TIKTOKEN_ENCODINGS_DIR=str(folder),
        TMP=str(temp),
        TEMP=str(temp),
        TMPDIR=str(temp),
        PYTHONPATH=str(_BACKEND),
        DATABASE_URL=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        CHROMA_PERSIST_DIR=str(tmp_path / "chroma"),
        CELERY_BROKER_URL="memory://",
        CELERY_RESULT_BACKEND="cache+memory://",
        HF_HUB_OFFLINE="1",
        PYTHONIOENCODING="utf-8",
    )
    done = subprocess.run(
        [sys.executable, "-c", _OFFLINE, module, TEXT],
        cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=600,
    )
    assert done.returncode == 0, done.stderr[-4000:]
    assert not (temp / "data-gym-cache").exists(), "tiktoken looked in the temp folder"
    return folder, done.stdout.splitlines()[-3:]


def test_the_worker_counts_offline_from_the_folder(tmp_path) -> None:
    folder, (chosen, count, asked) = _start_offline(tmp_path, "app.tasks.celery_app")
    assert chosen == str(folder.resolve())
    assert (count, asked) == (str(TOKENS), "0")


def test_the_api_counts_offline_from_the_folder(tmp_path) -> None:
    folder, (chosen, count, asked) = _start_offline(tmp_path, "app.main")
    assert chosen == str(folder.resolve())
    assert (count, asked) == (str(TOKENS), "0")


def test_the_default_folder_is_beside_the_apps_data() -> None:
    assert type(settings).model_fields["TIKTOKEN_ENCODINGS_DIR"].default == "./data/tiktoken"


# ---------------------------------------------------------------------------
# What use_app_folder decides
# ---------------------------------------------------------------------------


@pytest.fixture
def nothing_chosen(tmp_path, monkeypatch) -> Path:
    """No variable set and an empty temp folder. The suite's own choice comes
    back after: set, then removed, because monkeypatch restores only what it
    has seen, and ``use_app_folder`` writes the variable behind its back."""
    for name in ("TIKTOKEN_CACHE_DIR", "DATA_GYM_CACHE_DIR"):
        monkeypatch.setenv(name, "unset")
        monkeypatch.delenv(name)
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temp))
    return temp


def test_the_folder_is_what_tiktoken_reads_offline(nothing_chosen, tmp_path, monkeypatch) -> None:
    folder = tmp_path / "encodings"
    folder.mkdir()
    shutil.copyfile(_real_encoding(), folder / tiktoken_cache.cache_file())
    asked: list[str] = []

    def refuse(url, *args, **kwargs):
        asked.append(str(url))
        raise OSError(f"no network: {url}")

    assert tiktoken_cache.use_app_folder(str(folder)) == str(folder.resolve())
    # A fresh registry, or this reads the copy an earlier test left in memory.
    monkeypatch.setattr(tiktoken.registry, "ENCODINGS", {})
    monkeypatch.setattr(tiktoken.load, "read_file", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

    assert chunking._count_tokens(TEXT) == TOKENS
    assert asked == []
    assert not (nothing_chosen / "data-gym-cache").exists()


def test_the_first_run_downloads_into_the_folder(nothing_chosen, tmp_path, monkeypatch) -> None:
    folder = tmp_path / "data" / "tiktoken"
    monkeypatch.setattr(tiktoken.load, "read_file", lambda url: FAKE)

    tiktoken_cache.use_app_folder(str(folder))

    assert tiktoken.load.read_file_cached(tiktoken_cache.ENCODING_URL) == FAKE
    assert (folder / tiktoken_cache.cache_file()).read_bytes() == FAKE


def test_an_earlier_copy_needs_no_download(nothing_chosen, tmp_path, monkeypatch) -> None:
    old = nothing_chosen / "data-gym-cache" / tiktoken_cache.cache_file()
    old.parent.mkdir()
    old.write_bytes(FAKE)
    folder = tmp_path / "encodings"

    def refuse(url):
        raise AssertionError(f"requested {url}")

    monkeypatch.setattr(tiktoken.load, "read_file", refuse)
    tiktoken_cache.use_app_folder(str(folder))

    assert tiktoken.load.read_file_cached(tiktoken_cache.ENCODING_URL) == FAKE
    assert [p.name for p in folder.iterdir()] == [old.name], "no spare file left behind"


def test_a_copy_already_in_the_folder_is_kept(nothing_chosen, tmp_path) -> None:
    (nothing_chosen / "data-gym-cache").mkdir()
    (nothing_chosen / "data-gym-cache" / tiktoken_cache.cache_file()).write_bytes(b"older")
    folder = tmp_path / "encodings"
    folder.mkdir()
    (folder / tiktoken_cache.cache_file()).write_bytes(FAKE)

    tiktoken_cache.use_app_folder(str(folder))

    assert (folder / tiktoken_cache.cache_file()).read_bytes() == FAKE


@pytest.mark.parametrize("name", ["TIKTOKEN_CACHE_DIR", "DATA_GYM_CACHE_DIR"])
@pytest.mark.parametrize("value", ["somewhere/else", ""])
def test_a_folder_the_environment_chose_is_left_alone(nothing_chosen, tmp_path, monkeypatch, name, value) -> None:
    """The suite's arrangement (tests/tiktoken_cache.py) is one of these; an
    empty value is tiktoken's own way to turn caching off."""
    monkeypatch.setenv(name, value)
    folder = tmp_path / "encodings"

    assert tiktoken_cache.use_app_folder(str(folder)) is None

    both = ("TIKTOKEN_CACHE_DIR", "DATA_GYM_CACHE_DIR")
    assert {n: os.environ.get(n) for n in both} == {n: value if n == name else None for n in both}
    assert not folder.exists()


def test_the_suite_kept_its_own_folder() -> None:
    """conftest chose before the app imported, so the app left it alone and
    the suite never reads the install's folder."""
    assert suite_cache.chosen() is not None
    assert suite_cache.chosen() != str(Path(settings.TIKTOKEN_ENCODINGS_DIR).resolve())


def test_an_empty_setting_leaves_tiktokens_default(nothing_chosen) -> None:
    assert tiktoken_cache.use_app_folder("") is None
    assert "TIKTOKEN_CACHE_DIR" not in os.environ


def test_the_second_call_agrees_with_the_first(nothing_chosen, tmp_path) -> None:
    """The API imports the worker's module, so it calls twice."""
    folder = str(tmp_path / "encodings")
    first = tiktoken_cache.use_app_folder(folder)
    assert tiktoken_cache.use_app_folder(folder) == first == os.environ["TIKTOKEN_CACHE_DIR"]


def test_a_folder_that_cannot_be_made_leaves_tiktokens_default(nothing_chosen, tmp_path, monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(tiktoken_cache, "logger", logger)
    blocked = tmp_path / "data"
    blocked.write_text("a file where the folder would go", encoding="utf-8")

    assert tiktoken_cache.use_app_folder(str(blocked / "tiktoken")) is None

    assert "TIKTOKEN_CACHE_DIR" not in os.environ
    logger.warning.assert_called_once()


def test_a_folder_that_cannot_be_written_leaves_tiktokens_default(nothing_chosen, tmp_path, monkeypatch) -> None:
    """With the variable set, tiktoken raises when it cannot write what it
    downloaded, so the first job would fail at chunking."""
    logger = MagicMock()
    monkeypatch.setattr(tiktoken_cache, "logger", logger)

    def read_only(*args, **kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(tiktoken_cache.tempfile, "TemporaryFile", read_only)

    assert tiktoken_cache.use_app_folder(str(tmp_path / "encodings")) is None

    assert "TIKTOKEN_CACHE_DIR" not in os.environ
    logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Two processes downloading at once (review of #427)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "count",
    [chunking._count_tokens, knowledge_agent._count_tokens, report_agent._count_tokens],
    ids=["chunking", "knowledge_agent", "report_agent"],
)
def test_the_second_writer_counts_from_the_first_writers_copy(nothing_chosen, tmp_path, monkeypatch, count) -> None:
    """A fresh install: the API and the worker both miss the folder and
    download. The other one renames its copy into place while this one is
    still fetching, and this one's rename then meets a file, which on Windows
    raises (stood in for here, so the test means the same on every runner).
    tiktoken re-raises it for a folder the app chose. The count must still be
    right: chunking has no fallback and fails, and the agents' fallback counts
    words (3 here, not 5).

    Mutation check: calling ``tiktoken.get_encoding`` directly again in
    chunking, knowledge_agent or report_agent fails that case."""
    real = _real_encoding().read_bytes()
    folder = tmp_path / "encodings"
    assert tiktoken_cache.use_app_folder(str(folder)) == str(folder.resolve())
    copy = folder / tiktoken_cache.cache_file()
    downloads: list[str] = []

    def download(url):
        downloads.append(url)
        copy.write_bytes(real)  # the other process got there first
        return real

    rename = os.rename

    def rename_without_replacing(src, dst):
        if os.path.exists(dst):
            raise FileExistsError(errno.EEXIST, "Cannot create a file when that file already exists", src, None, dst)
        rename(src, dst)

    monkeypatch.setattr(tiktoken.registry, "ENCODINGS", {})
    monkeypatch.setattr(tiktoken.load, "read_file", download)
    monkeypatch.setattr(tiktoken.load.os, "rename", rename_without_replacing)

    assert count(TEXT) == TOKENS
    assert downloads == [tiktoken_cache.ENCODING_URL], "read from the folder, not fetched again"
    assert [p.name for p in folder.iterdir()] == [copy.name], "the spare download is not left behind"


def test_the_same_collision_twice_is_raised(nothing_chosen, tmp_path, monkeypatch) -> None:
    """One more load, not a loop and not a guess: a folder that keeps refusing
    the write fails the count."""
    folder = tmp_path / "encodings"
    tiktoken_cache.use_app_folder(str(folder))
    calls: list[str] = []

    def refuse(name):
        calls.append(name)
        raise FileExistsError(errno.EEXIST, "exists", str(folder / "x.tmp"), None, str(folder / "x"))

    monkeypatch.setattr(tiktoken, "get_encoding", refuse)
    with pytest.raises(FileExistsError):
        chunking._count_tokens(TEXT)
    assert calls == ["cl100k_base", "cl100k_base"]


def test_every_count_in_the_app_loads_through_the_one_helper() -> None:
    """A new ``tiktoken.get_encoding`` call would miss the collision above."""
    app = _BACKEND / "app"
    callers = sorted(
        str(path.relative_to(app)).replace(os.sep, "/")
        for path in app.rglob("*.py")
        if "tiktoken.get_encoding(" in path.read_text(encoding="utf-8")
    )
    assert callers == ["utils/tiktoken_cache.py"]


def test_this_repos_url_is_tiktokens(monkeypatch) -> None:
    asked: list[str] = []

    def record(url, expected_hash=None):
        asked.append(url)
        return {}

    monkeypatch.setattr(tiktoken_ext.openai_public, "load_tiktoken_bpe", record)
    tiktoken_ext.openai_public.cl100k_base()
    assert asked == [tiktoken_cache.ENCODING_URL]
    assert tiktoken_cache.cache_file() == suite_cache.cache_file()
