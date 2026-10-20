"""Export-file importers for Echo (S-3.7.5): the registry kind and its types.

An importer turns a file the user downloaded from another service (a WhatsApp
chat export, a Google Takeout archive) into items for the brain. Importers
are a registry kind of their own, separate from live connectors: they have no
``authorize_url`` and no sync, only

- ``accepts(source)`` — does this upload look like mine? (cheap: filename,
  zip member names, the first bytes);
- ``preview(source, options)`` — what an import would produce, without
  writing anything (counts, participants, warnings);
- ``parse(source, options)`` — yield the items, streaming: an importer never
  reads a whole member into memory, so a 100 MB export costs one line or one
  small JSON file at a time.

Items are ``ImportedShare`` today (shares inbox rows). Event and fact items
(``activity_events``, ``personal_context``) arrive with the importers that
need them.

**Authorship.** Every item says whose words it carries (``author_is_tenant``).
Third-party text, such as the other side of a WhatsApp thread, is stored as
context only: retrievable, never quoted verbatim in generated output, never
in a dataset export, and never a voice input (D-089).
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO, Any, Iterator, Protocol


class ExportUnreadable(ValueError):
    """The upload cannot be imported; the message is fit to show the user."""


@dataclass
class ImportedShare:
    """One shares-inbox row an importer produces."""

    content_type: str
    text: str
    author_is_tenant: bool
    occurred_at: datetime | None
    # Importer-specific provenance kept in raw_payload_json["import"].
    meta: dict[str, Any] = field(default_factory=dict)


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


class Importer(Protocol):
    name: str
    label: str

    def accepts(self, source: ImportSource) -> bool: ...

    def preview(self, source: ImportSource, options: dict[str, Any]) -> ImportPreview: ...

    def parse(
        self, source: ImportSource, options: dict[str, Any], stats: dict[str, int]
    ) -> Iterator[ImportedShare]:
        """Yield items; count what was deliberately left out in stats."""
        ...
