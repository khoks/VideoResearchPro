"""Process-global registry mapping `source_type` → connector instance.

Connectors register themselves at import time by calling `register(...)`.
The orchestrator looks them up via `connector_for(source_type)`.

Re-registering the same `source_type` overwrites the prior entry — useful
in tests for swapping in a fake connector.
"""
from __future__ import annotations

from app.sources.base import BaseConnector

_REGISTRY: dict[str, BaseConnector] = {}


def register(connector: BaseConnector) -> None:
    """Register a connector under its declared `source_type`."""
    if not isinstance(connector, BaseConnector):
        raise TypeError(
            f"register() expected BaseConnector, got {type(connector).__name__}"
        )
    _REGISTRY[connector.source_type] = connector


def connector_for(source_type: str) -> BaseConnector:
    """Return the registered connector for `source_type`.

    Raises `KeyError` if no connector has been registered.
    """
    try:
        return _REGISTRY[source_type]
    except KeyError as e:
        registered = sorted(_REGISTRY)
        raise KeyError(
            f"No connector registered for source_type={source_type!r}; "
            f"registered: {registered}"
        ) from e


def all_connectors() -> dict[str, BaseConnector]:
    """Return a copy of the registry (for diagnostics, health checks)."""
    return dict(_REGISTRY)


def _reset_for_tests() -> None:
    """Test-only escape hatch — clears the registry. Production code
    must not call this."""
    _REGISTRY.clear()
