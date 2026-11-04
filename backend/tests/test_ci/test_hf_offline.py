"""T-8.8.4.7 — the suite does not reach huggingface.co when the model is cached.

A DNS drop during a model load used to fail every test that embeds, although
the model was on disk. The first test here is the production caller: it loads
the model through ``embedding_service`` with lookups of the hub failing, the
way they do in a DNS drop. The others cover the choice made in conftest,
including the first run, which has to stay online or nothing can download.
"""
from __future__ import annotations

import socket
from pathlib import Path

import pytest

from app.config import settings
from app.services import embedding_service
from tests import hf_offline

MODEL = settings.EMBEDDING_MODEL_NAME
FILES = ("modules.json", "config.json", "tokenizer.json", "1_Pooling/config.json", "model.safetensors")
COMMIT = "abc123"
# Read at collection, before any test can download the model: a first run
# starts online and stays online, however early a test fills the cache.
CACHED_AT_START = hf_offline.model_is_cached(MODEL)


def _cache(root: Path, repo: str, files=FILES, ref: str | None = COMMIT) -> None:
    model = root / f"models--{repo.replace('/', '--')}"
    snapshot = model / "snapshots" / COMMIT
    for name in files:
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    if ref is not None:
        (model / "refs").mkdir(parents=True)
        (model / "refs" / "main").write_text(ref, encoding="utf-8")


@pytest.fixture
def hub(tmp_path, monkeypatch):
    """An empty hub cache, and no choice made yet."""
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    # Set, then removed: monkeypatch restores only what it has seen, and
    # stay_off_the_hub writes the variable behind its back.
    monkeypatch.setenv("HF_HUB_OFFLINE", "unset")
    monkeypatch.delenv("HF_HUB_OFFLINE")
    return tmp_path


def test_the_embedder_loads_with_the_hub_unreachable(monkeypatch) -> None:
    if not CACHED_AT_START:
        pytest.skip("first run here: the model was not cached at the start, so the suite is online")

    asked: list[str] = []
    resolve = socket.getaddrinfo

    def dropped(host, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else str(host)
        if name.endswith(("huggingface.co", "hf.co")):
            asked.append(name)
            raise socket.gaierror(socket.EAI_NONAME, f"DNS drop for {name}")
        return resolve(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", dropped)
    monkeypatch.setattr(embedding_service, "_model", None)
    vectors = embedding_service.encode(["a sentence to embed"])

    assert len(vectors) == 1 and len(vectors[0]) == 384
    assert asked == [], "loading a cached model asked the hub for something"


def test_a_cached_model_goes_offline(hub) -> None:
    _cache(hub, "sentence-transformers/some-model")
    assert hf_offline.stay_off_the_hub("some-model") is True
    assert hf_offline.os.environ["HF_HUB_OFFLINE"] == "1"


def test_a_model_with_its_own_organisation_is_found(hub) -> None:
    _cache(hub, "acme/embedder")
    assert hf_offline.model_is_cached("acme/embedder")
    assert not hf_offline.model_is_cached("embedder")


def test_the_first_run_stays_online(hub) -> None:
    assert hf_offline.stay_off_the_hub(MODEL) is False
    assert "HF_HUB_OFFLINE" not in hf_offline.os.environ


@pytest.mark.parametrize(
    "files",
    [
        [f for f in FILES if f != "model.safetensors"],  # the weights never arrived
        [f for f in FILES if f != "1_Pooling/config.json"],  # cut off near the end
    ],
)
def test_a_partial_download_is_not_cached(hub, files) -> None:
    _cache(hub, "sentence-transformers/some-model", files=files)
    assert hf_offline.stay_off_the_hub("some-model") is False


def test_a_snapshot_the_main_ref_does_not_name_is_not_cached(hub) -> None:
    _cache(hub, "sentence-transformers/some-model", ref=None)
    assert not hf_offline.model_is_cached("some-model")
    (hub / "models--sentence-transformers--some-model" / "refs").mkdir()
    (hub / "models--sentence-transformers--some-model" / "refs" / "main").write_text("otherhash", encoding="utf-8")
    assert not hf_offline.model_is_cached("some-model")


def test_a_value_already_chosen_is_left_alone(hub, monkeypatch) -> None:
    _cache(hub, "sentence-transformers/some-model")
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    assert hf_offline.stay_off_the_hub("some-model") is False
    assert hf_offline.os.environ["HF_HUB_OFFLINE"] == "0"

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    assert hf_offline.stay_off_the_hub("never-downloaded") is True


def test_the_cache_is_found_where_the_hub_looks(tmp_path, monkeypatch) -> None:
    for name in ("HF_HUB_CACHE", "HF_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert hf_offline.hub_cache() == tmp_path / ".cache" / "huggingface" / "hub"
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert hf_offline.hub_cache() == tmp_path / "xdg" / "huggingface" / "hub"
    monkeypatch.setenv("HF_HOME", str(tmp_path / "home"))
    assert hf_offline.hub_cache() == tmp_path / "home" / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    assert hf_offline.hub_cache() == tmp_path / "hub"
