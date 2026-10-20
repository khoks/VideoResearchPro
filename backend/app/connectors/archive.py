"""What archive importers share (S-3.7.5), beyond the ``ArchiveImporter``
contract in ``base``.

The contract is the minimum every importer meets: ``accepts(filename)`` and
``parse(stream, *, tenant_id)`` yielding ``ImportedShare`` / ``ActivityEvent``
/ ``DerivedFact``. The import flow (``echo_import_service``) also uses three
optional extras when an importer has them:

- ``sniff(source) -> bool`` — recognise the upload by its content (zip member
  names, the first lines) when the filename says nothing, for instance a
  renamed export;
- ``preview(source, options) -> ImportPreview`` — what an import would
  produce, without writing anything: counts, participants, warnings, and the
  options the importer understands with their defaults;
- keyword arguments on ``parse``: ``options`` (the user's choices),
  ``filename`` and ``stats`` (a dict the importer fills with what it
  deliberately left out, such as redacted turns).

An importer without them still works: detection falls back to its
``accepts(filename)`` and the preview to counting what ``parse`` yields.

Importers read through ``ImportSource``, which never extracts to disk and
refuses an archive that would unpack past ``ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES``,
so a 100 MB export costs one line or one small member at a time.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass, field
from typing import IO, Any


class ExportUnreadable(ValueError):
    """The upload cannot be imported; the message is fit to show the user."""


def stable_id(*parts: object) -> str:
    """A short id that is the same every time the same thing is imported, for
    ``ImportedShare.external_id``."""
    digest = hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return digest[:20]


@dataclass
class ImportPreview:
    importer: str
    label: str
    # Counts and facts the user should see before importing.
    summary: dict[str, Any] = field(default_factory=dict)
    # WhatsApp: who wrote what, so the user can say which name is theirs.
    participants: list[dict[str, Any]] = field(default_factory=list)
    # Options this importer understands, with their defaults.
    options: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class ImportSource:
    """One uploaded file, possibly a zip, read lazily and never extracted to
    disk. ``fileobj`` must be seekable (Starlette spools uploads to a
    temporary file, so it is)."""

    def __init__(self, fileobj: IO[bytes], filename: str, *, max_uncompressed: int):
        self.fileobj = fileobj
        self.filename = filename or "upload"
        self.max_uncompressed = max_uncompressed
        self._zip: zipfile.ZipFile | None = None
        self._is_zip: bool | None = None

    # -- shape ---------------------------------------------------------------

    @property
    def is_zip(self) -> bool:
        if self._is_zip is None:
            self.fileobj.seek(0)
            self._is_zip = zipfile.is_zipfile(self.fileobj)
            self.fileobj.seek(0)
        return self._is_zip

    @property
    def zip(self) -> zipfile.ZipFile:
        if self._zip is None:
            if not self.is_zip:
                raise ExportUnreadable("This file is not a zip archive.")
            self.fileobj.seek(0)
            try:
                self._zip = zipfile.ZipFile(self.fileobj)
            except zipfile.BadZipFile as e:
                raise ExportUnreadable("The zip archive is damaged.") from e
            total = sum(i.file_size for i in self._zip.infolist())
            if total > self.max_uncompressed:
                raise ExportUnreadable(
                    "The archive unpacks to more than "
                    f"{self.max_uncompressed // (1024 * 1024)} MB; import its parts separately."
                )
        return self._zip

    def check(self) -> None:
        """Refuse an archive that unpacks past the cap before any importer
        reads it (detection swallows errors, so it must not be first)."""
        if self.is_zip:
            self.zip  # noqa: B018 - opening it enforces the cap

    def member_names(self) -> list[str]:
        return [i.filename for i in self.zip.infolist() if not i.is_dir()] if self.is_zip else []

    def size(self) -> int:
        self.fileobj.seek(0, 2)
        n = self.fileobj.tell()
        self.fileobj.seek(0)
        return n

    def head(self, n: int = 4096) -> bytes:
        self.fileobj.seek(0)
        data = self.fileobj.read(n)
        self.fileobj.seek(0)
        return data

    # -- reading -------------------------------------------------------------

    def open_binary(self, member: str | None = None) -> IO[bytes]:
        if member is None:
            self.fileobj.seek(0)
            return _NonClosing(self.fileobj)
        return self.zip.open(member)

    def open_text(self, member: str | None = None) -> io.TextIOWrapper:
        """UTF-8 text, BOM stripped, undecodable bytes replaced, read line by
        line from the stream."""
        return io.TextIOWrapper(self.open_binary(member), encoding="utf-8-sig", errors="replace", newline=None)


class _NonClosing(io.RawIOBase):
    """Lets a TextIOWrapper wrap the upload without closing it on exit."""

    def __init__(self, raw: IO[bytes]):
        self._raw = raw

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:  # type: ignore[override]
        data = self._raw.read(len(b))
        n = len(data)
        b[:n] = data
        return n

    def close(self) -> None:  # leave the underlying file open
        super().close()
