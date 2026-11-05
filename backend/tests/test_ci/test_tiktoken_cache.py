"""T-8.8.6.1 — the suite counts tokens without reaching the network.

The first test is the production caller: it reloads the encoding through
``chunking._count_tokens`` with every request and lookup failing, the way they
do in a DNS drop. A real load is the only proof, because the file's name and
hash are tiktoken's business: the others hold this repo's copy of them to the
installed tiktoken, and cover what conftest chooses, the first run included.
"""
from __future__ import annotations

import hashlib
import os
import socket
from pathlib import Path

import pytest
import tiktoken.load
import tiktoken.registry
import tiktoken_ext.openai_public

from app.utils import chunking
from tests import tiktoken_cache

# Read at collection, before any test can download the file.
CACHED_AT_START = tiktoken_cache.encoding_is_cached()
FAKE = b"not the real encoding"


@pytest.fixture
def nothing_chosen(tmp_path, monkeypatch):
    """A machine where nothing has set the folder, with an empty home and an
    empty temp directory."""
    for name in ("TIKTOKEN_CACHE_DIR", "DATA_GYM_CACHE_DIR"):
        # Set, then removed: monkeypatch restores only what it has seen, and
        # use_stable_cache writes the variable behind its back.
        monkeypatch.setenv(name, "unset")
        monkeypatch.delenv(name)
    home, temp = tmp_path / "home", tmp_path / "temp"
    home.mkdir()
    temp.mkdir()
    monkeypatch.setattr(tiktoken_cache.Path, "home", lambda: home)
    monkeypatch.setattr(tiktoken_cache.tempfile, "gettempdir", lambda: str(temp))
    return home, temp


@pytest.fixture
def fake_encoding(monkeypatch) -> bytes:
    """Bytes that count as the encoding, so no test here copies 1.7 MB."""
    monkeypatch.setattr(tiktoken_cache, "ENCODING_SHA256", hashlib.sha256(FAKE).hexdigest())
    return FAKE


def _why_it_cannot_run(*, cached: bool, ci: bool) -> str | None:
    """On a machine a missing file is a first run. On a runner the download
    step has just put it there, so its absence is the bug."""
    if cached:
        return None
    if ci:
        pytest.fail(
            f"{tiktoken_cache.ENCODING} is not in the cache the run restored, so the suite downloaded it. "
            "Bump MODEL_CACHE_KEY in .github/workflows/ci.yml."
        )
    return "first run here: the encoding was not cached at the start"


def test_tokens_are_counted_with_the_network_down(monkeypatch) -> None:
    reason = _why_it_cannot_run(cached=CACHED_AT_START, ci=os.environ.get("GITHUB_ACTIONS") == "true")
    if reason:
        pytest.skip(reason)

    asked: list[str] = []

    def refuse(url, *args, **kwargs):
        asked.append(str(url))
        raise OSError(f"no network: {url}")

    # A fresh registry, or this reads the copy an earlier test left in memory.
    monkeypatch.setattr(tiktoken.registry, "ENCODINGS", {})
    monkeypatch.setattr(tiktoken.load, "read_file", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

    assert chunking._count_tokens("Echoes come back.") == 5
    assert asked == []


def test_a_missing_encoding_is_a_first_run_on_a_machine() -> None:
    assert "first run" in _why_it_cannot_run(cached=False, ci=False)


def test_a_missing_encoding_fails_on_a_runner() -> None:
    with pytest.raises(pytest.fail.Exception, match="MODEL_CACHE_KEY"):
        _why_it_cannot_run(cached=False, ci=True)


@pytest.mark.parametrize("ci", [True, False])
def test_a_cached_encoding_runs_everywhere(ci) -> None:
    assert _why_it_cannot_run(cached=True, ci=ci) is None


def test_conftest_chose_a_folder() -> None:
    """The suite never runs on tiktoken's temp default: that folder is what a
    runner starts empty and a machine clears."""
    assert tiktoken_cache.chosen() is not None


def test_this_repos_name_and_hash_are_tiktokens(monkeypatch) -> None:
    asked: list[tuple] = []

    def record(url, expected_hash=None):
        asked.append((url, expected_hash))
        return {}

    monkeypatch.setattr(tiktoken_ext.openai_public, "load_tiktoken_bpe", record)
    tiktoken_ext.openai_public.cl100k_base()
    assert asked == [(tiktoken_cache.ENCODING_URL, tiktoken_cache.ENCODING_SHA256)]


def test_the_first_run_downloads_into_the_stable_folder(nothing_chosen, monkeypatch) -> None:
    home, _ = nothing_chosen
    monkeypatch.setattr(tiktoken.load, "read_file", lambda url: FAKE)
    tiktoken_cache.use_stable_cache()

    assert tiktoken.load.read_file_cached(tiktoken_cache.ENCODING_URL) == FAKE
    assert (home / ".cache" / "tiktoken" / tiktoken_cache.cache_file()).read_bytes() == FAKE


def test_the_stable_folder_serves_the_next_run_with_no_request(nothing_chosen, monkeypatch) -> None:
    home, _ = nothing_chosen
    folder = home / ".cache" / "tiktoken"
    folder.mkdir(parents=True)
    (folder / tiktoken_cache.cache_file()).write_bytes(FAKE)

    def refuse(url):
        raise AssertionError(f"requested {url}")

    monkeypatch.setattr(tiktoken.load, "read_file", refuse)
    tiktoken_cache.use_stable_cache()
    assert tiktoken.load.read_file_cached(tiktoken_cache.ENCODING_URL) == FAKE


def test_a_copy_in_the_temp_folder_needs_no_download(nothing_chosen, fake_encoding) -> None:
    home, temp = nothing_chosen
    old = temp / "data-gym-cache" / tiktoken_cache.cache_file()
    old.parent.mkdir()
    old.write_bytes(fake_encoding)

    tiktoken_cache.use_stable_cache()

    folder = home / ".cache" / "tiktoken"
    assert os.environ["TIKTOKEN_CACHE_DIR"] == str(folder)
    assert (folder / old.name).read_bytes() == fake_encoding
    assert [p.name for p in folder.iterdir()] == [old.name], "no spare file left behind"
    assert tiktoken_cache.encoding_is_cached()


def test_a_broken_copy_in_the_temp_folder_is_not_brought_along(nothing_chosen, fake_encoding) -> None:
    home, temp = nothing_chosen
    old = temp / "data-gym-cache" / tiktoken_cache.cache_file()
    old.parent.mkdir()
    old.write_bytes(fake_encoding[:5])

    tiktoken_cache.use_stable_cache()

    assert not (home / ".cache" / "tiktoken" / old.name).exists()
    assert not tiktoken_cache.encoding_is_cached()


@pytest.mark.parametrize("name", ["TIKTOKEN_CACHE_DIR", "DATA_GYM_CACHE_DIR"])
@pytest.mark.parametrize("value", ["somewhere/else", ""])
def test_a_folder_someone_chose_is_left_alone(nothing_chosen, monkeypatch, name, value) -> None:
    home, _ = nothing_chosen
    monkeypatch.setenv(name, value)
    tiktoken_cache.use_stable_cache()

    assert os.environ[name] == value
    assert not (home / ".cache").exists()
    assert tiktoken_cache.chosen() == value


def test_caching_turned_off_is_not_cached(nothing_chosen, monkeypatch) -> None:
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", "")
    assert not tiktoken_cache.encoding_is_cached()


def test_a_home_that_cannot_be_written_leaves_tiktokens_default(nothing_chosen) -> None:
    """With the variable set, tiktoken raises when it cannot write the file.
    Without it, it does not."""
    home, _ = nothing_chosen
    (home / ".cache").write_text("a file where the folder would go", encoding="utf-8")
    tiktoken_cache.use_stable_cache()
    assert "TIKTOKEN_CACHE_DIR" not in os.environ


def test_warm_fills_the_folder_ci_caches(nothing_chosen, fake_encoding, monkeypatch) -> None:
    home, _ = nothing_chosen

    def fetched(name):
        folder = Path(os.environ["TIKTOKEN_CACHE_DIR"])
        (folder / tiktoken_cache.cache_file()).write_bytes(fake_encoding)

    monkeypatch.setattr("tiktoken.get_encoding", fetched)
    tiktoken_cache.warm()

    assert (home / ".cache" / "tiktoken" / tiktoken_cache.cache_file()).read_bytes() == fake_encoding


def test_warm_says_so_when_the_file_did_not_land(nothing_chosen, monkeypatch) -> None:
    monkeypatch.setattr("tiktoken.get_encoding", lambda name: None)
    with pytest.raises(SystemExit, match="cl100k_base"):
        tiktoken_cache.warm()
