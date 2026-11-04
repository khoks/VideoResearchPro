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
from typing import IO, Any, Callable, Iterator, Literal, Protocol, TypeVar, Union, runtime_checkable

T = TypeVar("T")
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
    logged, never exported. The token values stay out of ``repr``, so a debug
    line or a traceback cannot print them."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    expires_at: datetime | None = None
    scopes: str = ""
    # The provider account, for display ("octocat").
    account_label: str | None = None


@dataclass
class SyncContext:
    """Handed to a connector's sync methods. ``cursor`` is the connector's
    own resume state, persisted between syncs (start from it, write the new
    one back). ``facts`` collects derived facts for the runtime to store.

    A connector makes each provider call of a sync through ``call``, so a 401
    in the middle of a sync costs one renewal rather than a reconnect
    (T-3.2.1.12). ``renew`` is the runtime's: it is set when this grant can be
    renewed, returns the tokens to use, and raises ``ConnectorError`` when it
    cannot."""

    tenant_id: str
    tokens: ConnectorTokens
    cursor: dict[str, Any] = field(default_factory=dict)
    facts: list[DerivedFact] = field(default_factory=list)
    renew: Callable[[], ConnectorTokens] | None = field(default=None, repr=False, compare=False)
    _renewed: bool = field(default=False, init=False, repr=False, compare=False)

    def call(self, request: Callable[[str], T]) -> T:
        """Run ``request(access_token)``. On ``ConnectorError(auth=True)``
        renew the token and run it once more; that second refusal stands, so
        the user reconnects. One renewal per sync: a later 401 ends the sync
        without asking for a reconnect, since the token renewed a moment ago
        may simply have lapsed, and the next sync finds out."""
        try:
            return request(self.tokens.access_token)
        except ConnectorError as refused:
            if not refused.auth or self.renew is None:
                raise
            if self._renewed:
                raise TokenRenewalFailed(
                    "Sync failed: the provider refused a token renewed during this sync. The next sync tries again."
                ) from None
        self._renewed = True
        self.tokens = self.renew()
        return request(self.tokens.access_token)


class ConnectorError(RuntimeError):
    """The provider refused or failed. ``auth`` means the grant no longer
    works (revoked at the provider, expired) and the user must reconnect."""

    def __init__(self, message: str, *, auth: bool = False):
        super().__init__(message)
        self.auth = auth


class TokenRenewalFailed(ConnectorError):
    """The access token could not be renewed, for a reason the next sync may
    not share (the provider's token endpoint is down, another sync held the
    renewal too long). It ends the sync without asking for a reconnect. A
    connector that skips past a failed call must let this through, as it does
    an ``auth`` error."""


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


@runtime_checkable
class RefreshableConnector(Protocol):
    """Optional: a connector whose access tokens expire (Google's last an
    hour) implements this too (T-3.2.2.5). GitHub's do not expire, so it does
    not. Kept out of ``ActivityConnector`` so a connector without it still
    satisfies the contract.

    The runtime calls it before a sync once ``tokens.expires_at`` has passed
    and ``tokens.refresh_token`` is set, and when a provider call made through
    ``SyncContext.call`` answers 401; it stores what it returns encrypted. A
    returned ``refresh_token`` of None keeps the stored one (most providers
    do not rotate it). Raise ``ConnectorError(..., auth=True)`` when the
    provider refuses the refresh token (OAuth ``invalid_grant``: revoked,
    expired, or a testing-mode token past its seven days); the user must then
    reconnect. Any other ``ConnectorError`` is a failure the next sync
    retries.

    Readers of one grant take turns: the runtime claims the refresh per
    connector, so a provider that rotates refresh tokens sees each one spent
    once. Never put a token in an exception's message or a log line."""

    def refresh_tokens(self, tokens: ConnectorTokens) -> ConnectorTokens: ...


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
