"""Keep tiktoken's encoding where the next run finds it (T-8.8.6.1).

``tiktoken.get_encoding("cl100k_base")`` fetches about 1.7 MB from a public blob
store the first time, and keeps it in the system temp directory. That is
T-8.8.4.7's risk with two differences. A CI runner starts with an empty temp
directory, so CI fetched it on every run. And a fetch that fails is not always
an error: ``report_agent._count_tokens`` and ``knowledge_agent._count_tokens``
fall back to counting words, so a DNS drop can change what a test sees rather
than fail it.

The suite keeps the file in ``~/.cache/tiktoken``, beside the embedding models,
on a machine and in CI alike:

  * file there: tiktoken reads it, checks its hash and makes no request.
  * first run: the first test that counts tokens downloads it into that folder,
    and the next run has it. ``python -m tests.tiktoken_cache`` (from
    ``backend/``) does the same up front, and is what CI's download step runs on
    a cache miss.
  * a copy in tiktoken's temp folder from an earlier run: copied over, so a
    machine that already has the file needs no request.
  * ``TIKTOKEN_CACHE_DIR`` or ``DATA_GYM_CACHE_DIR`` already set, to anything:
    left alone. An empty value is tiktoken's own way to turn caching off.

Standard library only, and tiktoken is imported only by ``warm``: conftest runs
this before anything else, and it must not pay for tiktoken's import to do so.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

ENCODING = "cl100k_base"
# tiktoken_ext.openai_public.cl100k_base() names both, and has no constant for
# either. tests/test_ci/test_tiktoken_cache.py holds them to the installed copy.
ENCODING_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
ENCODING_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
_CHOICES = ("TIKTOKEN_CACHE_DIR", "DATA_GYM_CACHE_DIR")


def stable_dir() -> Path:
    """The folder a run keeps the encoding in unless told otherwise. CI's model
    cache lists this path, so it depends on nothing but the home directory."""
    return Path.home() / ".cache" / "tiktoken"


def cache_file() -> str:
    """The name tiktoken gives the encoding's file in its cache folder."""
    return hashlib.sha1(ENCODING_URL.encode()).hexdigest()


def _is_the_encoding(path: Path) -> bool:
    """A file that is cut off or corrupt does not count: tiktoken would throw
    it away and download, which is the request this module exists to avoid."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == ENCODING_SHA256
    except OSError:
        return False


def chosen() -> str | None:
    """The cache folder someone set, or None when nothing has."""
    return next((os.environ[name] for name in _CHOICES if name in os.environ), None)


def encoding_is_cached() -> bool:
    """Whether ``get_encoding`` can load the encoding without a request, from
    the folder this process would use."""
    folder = chosen()
    if folder is None:
        folder = str(_temp_default())
    return bool(folder) and _is_the_encoding(Path(folder) / cache_file())


def _temp_default() -> Path:
    """Where tiktoken keeps the file when nothing is set."""
    return Path(tempfile.gettempdir()) / "data-gym-cache"


def use_stable_cache() -> None:
    """Point tiktoken at ``stable_dir()`` unless something already chose. A
    home directory that cannot be written leaves tiktoken on its own default,
    which still works: with the variable set, a failed write would raise."""
    if chosen() is not None:
        return
    folder = stable_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        _copy_from_temp(folder / cache_file())
    except OSError:
        return
    os.environ["TIKTOKEN_CACHE_DIR"] = str(folder)


def _copy_from_temp(target: Path) -> None:
    old = _temp_default() / target.name
    if target.exists() or not _is_the_encoding(old):
        return
    # Under a name of its own, then in one step: parallel suites can both be here.
    spare = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    shutil.copyfile(old, spare)
    os.replace(spare, target)


def warm() -> None:
    """Have the encoding on disk now: CI's download step, or by hand before
    working offline."""
    use_stable_cache()
    import tiktoken

    tiktoken.get_encoding(ENCODING)
    if not encoding_is_cached():
        raise SystemExit(f"{ENCODING} is not in {chosen() or _temp_default()} after loading it.")


if __name__ == "__main__":
    warm()
