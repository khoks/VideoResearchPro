"""The `BaseConnector` abstract base class — every source-type connector
must subclass this and implement at minimum `search`, `list_creator_items`,
`fetch_metadata`, and `fetch_text`.

`fetch_creator` is optional and returns None by default for source types
that don't have a creator concept (e.g. user-uploaded PDFs).

Connectors are stateless apart from constructor-injected dependencies
(API clients, rate limiters, settings). They never touch the database
directly — persisting normalized Candidates / ExtractedText into the
`videos` (eventually `documents`) table is the job orchestrator's job.
"""
from __future__ import annotations

import abc
from datetime import datetime
from typing import ClassVar, Iterable

from app.sources.types import Candidate, CreatorMetadata, ExtractedText, SourceMetadata


class BaseConnector(abc.ABC):
    """Contract every source-type connector implements."""

    #: The source-type discriminator string (`"video"`, `"article"`, …).
    #: Must match `documents.source_type` values in the schema.
    source_type: ClassVar[str]

    @abc.abstractmethod
    def search(
        self,
        query: str,
        instructions: str = "",
        limit: int = 10,
    ) -> list[Candidate]:
        """Discovery — return a ranked list of candidates for `query`.

        `instructions` is optional free-text context the user wrote on the
        submit-research form (e.g. "focus on macroeconomic angles") that
        the connector may use to refine results.

        Connectors that do not support search (e.g. PDF, where the user
        uploads files directly) raise `NotImplementedError`.
        """

    @abc.abstractmethod
    def list_creator_items(
        self,
        creator_external_id: str,
        since: datetime | None = None,
        *,
        limit: int | None = None,
        job_id: str = "",
    ) -> Iterable[Candidate]:
        """List items by a creator (channel/show/feed/etc.).

        Used by both manual channel jobs (with `limit`) and subscription
        jobs (no `limit`, walk every page). When `since` is set, return
        only items published after that timestamp.

        `job_id` is forwarded for log correlation only.
        """

    @abc.abstractmethod
    def fetch_metadata(
        self,
        source_ids: list[str],
        *,
        job_id: str = "",
    ) -> dict[str, SourceMetadata]:
        """Batch-fetch metadata for a list of source IDs.

        Returns a `{source_id: SourceMetadata}` mapping. Missing IDs are
        omitted from the result rather than raising.

        `job_id` is forwarded for log correlation only.
        """

    @abc.abstractmethod
    def fetch_text(
        self,
        candidate: Candidate,
        *,
        job_id: str = "",
    ) -> ExtractedText | None:
        """Fetch the full text payload for `candidate`.

        Returns `None` when the text is unavailable (paywall, removed,
        connector failure) — the orchestrator marks the document as
        `text_status='unavailable'` rather than raising.

        `job_id` is forwarded for log correlation only; connectors should
        not branch on it.
        """

    def fetch_creator(self, creator_external_id: str) -> CreatorMetadata | None:
        """Optional: fetch creator metadata for the `creators` table.

        Default implementation returns None. Connectors with a creator
        concept (YouTube channel, podcast show, RSS feed) override this.
        """
        return None

    def resolve_creator_id(self, hint: str, *, job_id: str = "") -> str | None:
        """Optional: resolve a free-text hint (URL, handle, name, raw ID)
        to the canonical `creator_external_id` this connector uses
        internally.

        E.g. for YouTube: `"https://youtube.com/@channel"` → `"UCxxx..."`.
        For podcasts: `"The Daily"` → an Apple/Spotify show ID.

        Default implementation returns None — connectors without a
        creator concept (PDFs) leave this unimplemented.
        """
        return None
