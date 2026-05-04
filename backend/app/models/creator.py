"""Creator ORM — going-forward name for the Channel class (E-1.9).

The class lives in :mod:`app.models.channel` for historical reasons (the
table was originally `channels` and YouTube-only). E-1.9 generalises
the concept to "creator" — any source-content producer (YouTube
channel, podcast show, blog domain, X author, RSS feed). The class
itself already carries the L1 multi-source columns (``source_type``,
``creator_external_id``, ``source_weight``, ``creator_metadata_json``)
so it's structurally Creator-shaped today; only the name needs to
catch up.

**Strategy.** Per [D-032](../../../docs/decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03)
precedent (operator-coordinated runbook for data-bearing renames),
the Python-level alias ships immediately so all new code can
``from app.models.creator import Creator``. The actual SQL-table
rename (`channels` → `creators` + `documents.channel_id` →
`documents.creator_id`) happens later via the operator-coordinated
runbook at :file:`docs/migration-channels-to-creators.md`. The Python
alias works against either schema — when the table rename runs, only
the ORM's ``__tablename__`` updates, and the Python `Creator` /
`Channel` class names continue to resolve correctly.

**Migration ordering for new code.**

- New code should import ``Creator`` from this module.
- Existing code importing ``Channel`` from ``app.models.channel`` keeps
  working — `Channel` remains a back-compat alias indefinitely.
- The legacy `Channel` name will not be removed in v1 of the SaaS
  rollout — too much existing code references it. A future
  migration can migrate imports en masse if desired.
"""
from app.models.channel import Channel as Creator

__all__ = ["Creator"]
