"""The two ways data enters Echo from outside (S-3.2.1, `personal-brain.md`
§ Connector interface contract).

**Activity connectors** (``ActivityConnector``) pull from a provider over
OAuth on a schedule: GitHub (S-3.2.4), later YouTube likes and Calendar. They
live in ``app/connectors/<name>/`` and register themselves with
``registry.register_connector``. The runtime
(``echo_connector_service``) owns everything around them: the consent screen,
the OAuth state and PKCE, the encrypted tokens, idempotent storage, the
schedule and revoke. A connector only talks to its provider and turns what it
gets into ``ActivityEvent`` values.

**Archive importers** (``ArchiveImporter``) parse a file the user exported
themselves (Takeout, WhatsApp, Spotify's extended history, Strava's bulk
export): no OAuth, no schedule, never a fake ``authorize_url``. They register
with ``registry.register_importer`` and yield events, shares or facts; the
import flow is S-3.7.5.

Review checklist for any new connector (`personal-brain.md`): the consent
disclosure is plain language, revoke deletes data rather than stopping sync,
incremental sync is idempotent, and the privacy weight is honest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import IO, Any, Iterator, Literal, Protocol, Union, runtime_checkable

PrivacyWeight = Literal["low", "medium", "high", "very_high"]


@dataclass(frozen=True)
class ActivityEvent:
    """One event as a connector or importer produces it, before storage.

    ``external_id`` must be stable for the same real-world event across
    syncs; it is what makes storage idempotent. ``text_content`` carries only
    the user's own words (commit messages, PR descriptions), never third-party
    text."""

    external_id: str
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    text_content: str | None = None
    linked_document_id: str | None = None


@dataclass(frozen=True)
class DerivedFact:
    """A fact inferred from activity (``skill`` from languages, ``interest``
    from channels). Always below 1.0 confidence: it is a guess, and the
    user's own statements outrank it."""

    kind: str
    key: str
    value: Any
    confidence: float


@dataclass
class ConnectorTokens:
    """What a successful OAuth callback returns. Stored encrypted; never
    logged, never exported."""

    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scopes: str = ""
    # The provider account, for display ("octocat").
    account_label: str | None = None


@dataclass
class SyncContext:
    """Handed to a connector's sync methods. ``cursor`` is the connector's
    own resume state, persisted between syncs (start from it, write the new
    one back). ``facts`` collects derived facts for the runtime to store."""

    tenant_id: str
    tokens: ConnectorTokens
    cursor: dict[str, Any] = field(default_factory=dict)
    facts: list[DerivedFact] = field(default_factory=list)


class ConnectorError(RuntimeError):
    """The provider refused or failed. ``auth`` means the grant no longer
    works (revoked at the provider, expired) and the user must reconnect."""

    def __init__(self, message: str, *, auth: bool = False):
        super().__init__(message)
        self.auth = auth


@runtime_checkable
class ActivityConnector(Protocol):
    name: str  # stored as activity_events.connector; matches app/connectors/<name>/
    display_name: str
    privacy_weight: PrivacyWeight
    # The one-screen text shown before the OAuth redirect, and its version:
    # the grant records which version the user agreed to.
    consent_disclosure: str
    consent_version: str
    # Whether syncs run on the scheduler, and how often (scheduler cadence).
    schedule: dict[str, Any] | None

    def event_types(self) -> list[str]: ...

    def is_configured(self) -> bool:
        """Whether the install has this connector's OAuth client."""

    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: str) -> str: ...

    def handle_callback(self, *, code: str, redirect_uri: str, code_verifier: str) -> ConnectorTokens: ...

    def revoke(self, tokens: ConnectorTokens) -> None:
        """Revoke the grant at the provider. Best effort: local data is
        deleted whether or not this succeeds."""

    def initial_backfill(self, ctx: SyncContext) -> Iterator[ActivityEvent]: ...

    def incremental_sync(self, ctx: SyncContext, since: datetime | None) -> Iterator[ActivityEvent]: ...


@dataclass(frozen=True)
class ImportedShare:
    """Something the user handed over, from an export file (a WhatsApp
    message, a saved article). Becomes a ``shares_inbox`` row; third-party
    words stay context-only unless ``author_is_tenant`` (D-089)."""

    external_id: str
    occurred_at: datetime
    text: str | None = None
    url: str | None = None
    title: str | None = None
    author: str | None = None
    author_is_tenant: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


ImportedItem = Union[ActivityEvent, ImportedShare, DerivedFact]


@runtime_checkable
class ArchiveImporter(Protocol):
    name: str  # stored as activity_events.connector for the events it yields
    display_name: str
    privacy_weight: PrivacyWeight
    consent_disclosure: str

    def accepts(self, filename: str) -> bool:
        """Whether this importer recognises the file (by name or extension)."""

    def parse(self, stream: IO[bytes], *, tenant_id: str) -> Iterator[ImportedItem]: ...
