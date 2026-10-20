"""Echo export-file importers (S-3.7.5). See ``base`` for the contract.

``IMPORTERS`` is the registry, in detection order: the first importer whose
``accepts`` says yes handles an upload, unless the caller names one.
"""
from __future__ import annotations

from types import ModuleType

from app.services.echo_importers import google_keep, whatsapp
from app.services.echo_importers.base import (
    ImportedShare,
    ExportUnreadable,
    ImportPreview,
    ImportSource,
)

IMPORTERS: dict[str, ModuleType] = {
    whatsapp.NAME: whatsapp,
    google_keep.NAME: google_keep,
}


def detect(source: ImportSource) -> ModuleType | None:
    for importer in IMPORTERS.values():
        if importer.accepts(source):
            return importer
    return None


def get(name: str) -> ModuleType:
    try:
        return IMPORTERS[name]
    except KeyError:
        raise ExportUnreadable(f"Unknown importer {name!r}.") from None


__all__ = ["IMPORTERS", "ImportedShare", "ExportUnreadable", "ImportPreview", "ImportSource", "detect", "get"]
