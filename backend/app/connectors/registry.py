"""The connector and importer registries (S-3.2.1).

Connectors register when their package is imported; ``load_builtin`` imports
every package under ``app/connectors/`` so the API and the worker see the same
set. Registration is idempotent on ``name``.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

logger = logging.getLogger(__name__)

_CONNECTORS: dict[str, Any] = {}
_IMPORTERS: dict[str, Any] = {}
_loaded = False


def register_connector(connector: Any) -> None:
    _CONNECTORS[connector.name] = connector


def unregister_connector(name: str) -> None:
    _CONNECTORS.pop(name, None)


def get_connector(name: str) -> Any | None:
    return _CONNECTORS.get(name)


def list_connectors() -> list[str]:
    return sorted(_CONNECTORS)


def connectors() -> list[Any]:
    return [_CONNECTORS[n] for n in sorted(_CONNECTORS)]


def register_importer(importer: Any) -> None:
    _IMPORTERS[importer.name] = importer


def unregister_importer(name: str) -> None:
    _IMPORTERS.pop(name, None)


def get_importer(name: str) -> Any | None:
    return _IMPORTERS.get(name)


def list_importers() -> list[str]:
    return sorted(_IMPORTERS)


def importer_for(filename: str) -> Any | None:
    """The first registered importer (by name) that accepts ``filename``."""
    for name in sorted(_IMPORTERS):
        importer = _IMPORTERS[name]
        try:
            if importer.accepts(filename):
                return importer
        except Exception:
            logger.exception("importer %s failed on accepts(%r)", name, filename)
    return None


def load_builtin() -> None:
    """Import every connector package under ``app/connectors/`` once."""
    global _loaded
    if _loaded:
        return
    import app.connectors as pkg

    for info in pkgutil.iter_modules(pkg.__path__):
        if info.ispkg:
            try:
                importlib.import_module(f"app.connectors.{info.name}")
            except Exception:
                logger.exception("connector package %s failed to load", info.name)
    _loaded = True
