"""Multi-source connector dispatch for topic jobs.

Per [D-020](../../../docs/decisions.md#d-020) (resolves OQ-10), this
module owns the *search-phase fan-out* for topic jobs that target one
or more source types. Today the legacy job pipeline hardcodes YouTube;
M-1.5 (Reddit + HN end-to-end MVP) requires that the orchestrator
dispatches by `source_type` through the connector registry instead.

Why a dedicated module (and not just inline in `app/tasks/job_tasks.py`):
the dispatch layer ships once and is reused by every future connector
(Mastodon, Bluesky, Mode B paste, podcasts, PDFs). Folding into per-
source storage tasks (the alternative considered in D-020) would
duplicate the dispatch pattern N times.

Per [D-023](../../../docs/decisions.md#d-023), *classification* of
fetched candidates happens **inline** inside each connector's
`fetch_text()`. This dispatcher is concerned with the search-phase
fan-out only — collecting Candidates from each source type's
connector and merging them into a unified approval queue.

Today's implementation is **sequential**: each `source_type` is
dispatched in turn. The fan-out semantics decision (round-robin vs
parallel) is T-1.5.11.3's concern; this module ships the interface
and a sensible-default sequential implementation. Per-source rate-
limit / retry config (T-1.5.11.2) and progress-reporting parity
(T-1.5.11.4) are also separate tasks that build on the surface
established here.

Connector errors are caught and recorded per-source-type — one
connector's failure must not crash a multi-source job. The orchestrator
inspects `DispatchResult.errors_by_source_type` to decide whether
to surface a degraded-mode warning.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

from app.sources.registry import connector_for
from app.sources.types import Candidate

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    """Per-source-type result of a search dispatch.

    `candidates_by_source_type` is keyed by `source_type` (`"video"`,
    `"reddit_post"`, `"hn_story"`, …). Source types whose connector
    raised land in `errors_by_source_type` AND get an empty list in
    `candidates_by_source_type` so callers can still iterate uniformly.

    `errors_by_source_type` carries a string describing each failure
    (`"<ExceptionType>: <message>"` or a context-specific message
    like `"No connector registered for 'mastodon_post'"`). Empty when
    the dispatch ran fully clean.
    """

    candidates_by_source_type: dict[str, list[Candidate]] = field(default_factory=dict)
    errors_by_source_type: dict[str, str] = field(default_factory=dict)

    def all_candidates(self) -> list[Candidate]:
        """Flatten the per-source-type candidates into a single list,
        preserving the order in which source_types were dispatched."""
        out: list[Candidate] = []
        for cands in self.candidates_by_source_type.values():
            out.extend(cands)
        return out

    @property
    def total_count(self) -> int:
        """Total candidates across all source types."""
        return sum(len(c) for c in self.candidates_by_source_type.values())

    @property
    def has_errors(self) -> bool:
        """True iff any source-type connector raised or was missing."""
        return bool(self.errors_by_source_type)


def dispatch_search(
    source_types: Iterable[str],
    query: str,
    instructions: str = "",
    limit_per_type: int = 10,
    *,
    job_id: str = "",
) -> DispatchResult:
    """Run `search()` on every connector for `source_types` and merge.

    Sequential today; T-1.5.11.3 will decide whether to switch to
    parallel fan-out (recommended in the OQ-15 plan: parallel with
    per-type rate-limit guarding so overall job latency tracks the
    slowest source rather than the sum).

    Args:
        source_types: e.g. ``["video", "reddit_post", "hn_story"]``.
            Iteration order is preserved in the merged candidate list.
            Duplicates are NOT deduplicated — caller decides whether
            to filter (today's behaviour: pass through, since duplicate
            entries would be unusual for a topic search).
        query: topic search query.
        instructions: free-text user instructions forwarded to each
            connector's `search()`.
        limit_per_type: per-source-type candidate cap.
        job_id: forwarded for log correlation only.

    Returns:
        ``DispatchResult`` with per-source-type candidates + errors.
        Always returns a result; never raises (connector failures
        are captured in ``errors_by_source_type``).
    """
    candidates_by_type: dict[str, list[Candidate]] = {}
    errors_by_type: dict[str, str] = {}

    for st in source_types:
        try:
            connector = connector_for(st)
        except KeyError as e:
            errors_by_type[st] = str(e)
            candidates_by_type[st] = []
            logger.warning(
                "dispatch_search: %s",
                str(e),
                extra={"job_id": job_id},
            )
            continue

        try:
            cands = list(
                connector.search(
                    query=query,
                    instructions=instructions,
                    limit=limit_per_type,
                )
            )
        except NotImplementedError:
            # Connectors like PDF that don't support search return
            # NotImplementedError per the BaseConnector contract.
            # Treat as zero candidates, not an error worth surfacing.
            candidates_by_type[st] = []
            logger.info(
                "dispatch_search: connector %r does not support search()",
                st,
                extra={"job_id": job_id},
            )
            continue
        except Exception as e:
            errors_by_type[st] = f"{type(e).__name__}: {e}"
            candidates_by_type[st] = []
            logger.exception(
                "dispatch_search: connector %r raised during search()",
                st,
                extra={"job_id": job_id},
            )
            continue

        candidates_by_type[st] = cands
        logger.info(
            "dispatch_search: %s returned %d candidates",
            st,
            len(cands),
            extra={"job_id": job_id},
        )

    return DispatchResult(
        candidates_by_source_type=candidates_by_type,
        errors_by_source_type=errors_by_type,
    )
