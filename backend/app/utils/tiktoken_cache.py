"""Where tiktoken keeps its encoding in the API and the worker (T-8.8.6.5).

At the first token count, ``tiktoken.get_encoding("cl100k_base")`` fetches about
1.7 MB from a public blob store and keeps it in ``<temp>/data-gym-cache``,
unless ``TIKTOKEN_CACHE_DIR`` or ``DATA_GYM_CACHE_DIR`` names a folder. A temp
folder is what a cleanup empties, and ``chunking._count_tokens`` has no
fallback, so an emptied temp folder and a network drop together failed a job
at chunking. A fallback that counted words would cut chunks of the wrong size
without a word said, so there is none: the file is kept where nothing clears it.

``use_app_folder`` points tiktoken at ``TIKTOKEN_ENCODINGS_DIR``
(``./data/tiktoken``, beside the app's other data). The API and the worker call
it while they import, before anything counts a token:

* ``TIKTOKEN_CACHE_DIR`` or ``DATA_GYM_CACHE_DIR`` already in the environment,
  set to anything: left alone. That is how the test suite keeps its own folder
  (``tests/tiktoken_cache.py``, T-8.8.6.1), and an empty value is tiktoken's own
  way to turn caching off.
* the setting empty: left alone, so tiktoken uses its temp folder as before.
* a copy in tiktoken's temp folder: copied over, so an install that has run
  before needs no request after this change. tiktoken checks the hash when it
  reads, and replaces a bad copy by downloading.
* otherwise the first count downloads into the folder, as a fresh install
  always has.
* a folder that cannot be made or written: a warning, and tiktoken stays on its
  temp default. With the variable set, tiktoken raises when it cannot write
  the file it downloaded, and the job would fail at chunking instead.

Every count in the app loads its encoding through ``encoding``, which survives
the one write that can collide: two processes downloading at once on a fresh
install (its docstring says how). A test pins that nothing else in ``app/``
calls ``tiktoken.get_encoding``.

Standard library only at import: tiktoken is imported when ``encoding`` is
first called, and the variable is read when an encoding loads, not when the
module does.
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

VARIABLE = "TIKTOKEN_CACHE_DIR"
_CHOICES = (VARIABLE, "DATA_GYM_CACHE_DIR")
# The encoding every count in the app uses. tiktoken_ext.openai_public names
# its URL and has no constant for it; tests/test_utils/test_tiktoken_folder.py
# holds this copy to the installed one.
ENCODING = "cl100k_base"
ENCODING_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"


def cache_file() -> str:
    """The name tiktoken gives the encoding's file in its cache folder."""
    return hashlib.sha1(ENCODING_URL.encode()).hexdigest()


def encoding(name: str = ENCODING):
    """``tiktoken.get_encoding(name)``, surviving a lost race to the folder.

    tiktoken writes what it downloaded under a name of its own, then renames
    that into place. Under its temp default it swallows an error from that
    write; with the folder chosen here it re-raises it, as it does for any
    folder named in the environment. On Windows a rename onto a file that
    exists raises ``FileExistsError``, and tiktoken's lock covers the threads
    of one process, not two. So on a fresh install the API (a PDF is chunked
    in the request) and the worker can both miss the folder, both download, and
    the one that renames second would fail its count, a 500 or a failed job.

    The file it lost to is in the folder by then, so the load runs once more and
    reads it, hash checked as tiktoken always does. Any other error, or the same
    one twice, is raised: nothing here counts tokens another way."""
    import tiktoken

    try:
        return tiktoken.get_encoding(name)
    except FileExistsError as exc:
        _discard_spare(exc)
        logger.info("tiktoken: another process saved %s first; reading its copy", name)
        return tiktoken.get_encoding(name)


def _discard_spare(exc: FileExistsError) -> None:
    """Remove the file this process downloaded and could not rename, which
    tiktoken leaves behind. Only a rename's source (an error with two names)
    whose name ends ``.tmp``, as tiktoken's spare does, is touched."""
    spare = exc.filename
    if exc.filename2 is None or not isinstance(spare, str) or not spare.endswith(".tmp"):
        return
    with contextlib.suppress(OSError):
        os.remove(spare)


def use_app_folder(folder: str) -> str | None:
    """Point tiktoken at ``folder`` unless the environment already chose one.

    Returns the folder tiktoken will read, or None when it was left alone.
    Never raises: the worst case is tiktoken's own default, as before."""
    target = Path(folder).resolve() if folder else None
    current = next((name for name in _CHOICES if name in os.environ), None)
    if current is not None:
        # The API imports the worker's module too, so the second call lands
        # here, on the folder the first one set.
        return os.environ[current] if target is not None and os.environ[current] == str(target) else None
    if target is None:
        return None
    try:
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=target):
            pass
    except OSError as exc:
        logger.warning(
            "tiktoken: cannot keep its encoding in %s (%s); it stays in the temp folder", target, exc
        )
        return None
    _copy_from_temp(target / cache_file())
    os.environ[VARIABLE] = str(target)
    return str(target)


def _copy_from_temp(path: Path) -> None:
    """Bring an earlier run's copy over. A failure only means a download."""
    old = Path(tempfile.gettempdir()) / "data-gym-cache" / path.name
    if path.exists() or not old.is_file():
        return
    # Under a name of its own, then in one step: the API and the worker start
    # together and can both be here.
    spare = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(old, spare)
        os.replace(spare, path)
    except OSError:
        with contextlib.suppress(OSError):
            spare.unlink(missing_ok=True)
