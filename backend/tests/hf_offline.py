"""Keep the suite off huggingface.co once the embedding model is cached (T-8.8.4.7).

Loading a cached model still sends HEAD requests to the hub. A DNS drop during
one fails the test (9 failures in one #398 run), even though every byte the
test needs is on disk. ``HF_HUB_OFFLINE=1`` stops those requests, but with no
model in the cache it turns the first run's download into an error, so it is
set only when the model is there:

  * model cached: offline, nothing reaches the hub.
  * first run: online, the first test that embeds downloads the model, and the
    next run is offline.
  * ``HF_HUB_OFFLINE`` already set, to anything: left alone. CI sets ``1``, so a
    bad model cache fails loudly instead of downloading at test time.
    ``HF_HUB_OFFLINE=0`` forces a hub check here.

Standard library only, on purpose: huggingface_hub reads ``HF_HUB_OFFLINE``
once, when it is imported, so this has to run before that import, and asking
the library whether the model is cached would be that import.
"""
from __future__ import annotations

import os
from pathlib import Path

# What sentence-transformers opens for this model. A cache holding only some of
# them (a download cut off part way) must not count as cached: offline, the
# missing file is an error, online it is a download.
_REQUIRED = ("modules.json", "config.json", "tokenizer.json", "1_Pooling/config.json")
_WEIGHTS = ("model.safetensors", "pytorch_model.bin")
_TRUE = ("1", "ON", "YES", "TRUE")


def hub_cache() -> Path:
    """The hub's cache directory, resolved as huggingface_hub.constants does."""
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"]).expanduser()
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]).expanduser() / "hub"
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base).expanduser() / "huggingface" / "hub"


def model_is_cached(name: str) -> bool:
    """Whether every file ``SentenceTransformer(name)`` opens is on disk, in
    the snapshot the hub's ``main`` ref points at."""
    # A bare name is sentence-transformers' own organisation on the hub.
    repo = name if "/" in name else f"sentence-transformers/{name}"
    root = hub_cache() / f"models--{repo.replace('/', '--')}"
    try:
        snapshot = root / "snapshots" / (root / "refs" / "main").read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return all((snapshot / f).is_file() for f in _REQUIRED) and any((snapshot / f).is_file() for f in _WEIGHTS)


def _offline() -> bool:
    return os.environ.get("HF_HUB_OFFLINE", "").strip().upper() in _TRUE


def online_by_choice() -> bool:
    """Whether ``HF_HUB_OFFLINE`` was set to a value that keeps the hub on.
    Not the same as being online: a cached model with no value at all means
    ``stay_off_the_hub`` never ran, which is a bug, not a choice."""
    return "HF_HUB_OFFLINE" in os.environ and not _offline()


def stay_off_the_hub(model_name: str) -> bool:
    """Set ``HF_HUB_OFFLINE=1`` when ``model_name`` is cached and nothing has
    chosen a value. Returns whether the suite is offline."""
    if "HF_HUB_OFFLINE" not in os.environ and model_is_cached(model_name):
        os.environ["HF_HUB_OFFLINE"] = "1"
    return _offline()
