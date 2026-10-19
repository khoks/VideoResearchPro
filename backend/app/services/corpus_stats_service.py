"""Corpus statistics for Q&A — the figures the length policy and the
temporal note are computed from (S-1.15.2 / T-1.17.1.4).

`report_agent.compute_statistics` derives the same figures from the chunks
in front of it at report time. Q&A has no chunks in hand until retrieval,
and retrieval returns a handful of hits, not the corpus — so the policy
needs the figures from the DATABASE: the approved document set for a job,
the visible document set for library-wide questions (D-063).

The shape mirrors the report's `statistics` dict for the keys both consume
(`video_count`, `total_words`, `earliest_published`, `latest_published`,
`median_published`, `videos_by_year`, `dated_video_count`) plus the era
summary, so `output_length.corpus_bracket` and the prompt notes read one
shape from both producers.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from app.models.document import Document
from app.models.job_video import JobVideo
from app.services import temporal_service

logger = logging.getLogger(__name__)

_SQL_IN_CHUNK = 500


def empty_statistics() -> dict:
    return {
        "video_count": 0,
        "total_words": 0,
        "earliest_published": None,
        "latest_published": None,
        "median_published": None,
        "videos_by_year": {},
        "dated_video_count": 0,
        **temporal_service.summarize_eras([]),
    }


def corpus_statistics_for_document_ids(db: Any, document_ids: Iterable[str]) -> dict:
    """Statistics for an explicit document set. Empty set -> zero statistics.

    ``document_ids`` are ``documents.document_id`` values (D-070) — the legacy
    ``video_id`` is NULL for every non-video source, so a set keyed on it
    would silently omit PDFs and pasted pages from the figures.

    Zero statistics classify as the `small` bracket, which is correct for a
    job with no approved documents — not a fallback to be papered over.
    """
    ids = sorted({d for d in document_ids if d})
    if not ids:
        return empty_statistics()

    rows: list = []
    for i in range(0, len(ids), _SQL_IN_CHUNK):
        rows.extend(
            db.query(
                Document.document_id,
                Document.transcript_word_count,
                Document.word_count,
                Document.published_at,
                Document.discussed_era_json,
            )
            .filter(Document.document_id.in_(ids[i:i + _SQL_IN_CHUNK]))
            .all()
        )

    total_words = 0
    dates: list[str] = []
    eras: list[dict | None] = []
    seen: set[str] = set()
    for did, t_words, words, published_at, era_raw in rows:
        if did in seen:
            continue
        seen.add(did)
        total_words += int(t_words or words or 0)
        shown = temporal_service.published_display(published_at)
        if shown:
            dates.append(shown)
        eras.append(temporal_service.load_era(temporal_service._EraRow(era_raw)))

    dates.sort()
    year_counts: dict[str, int] = {}
    for d in dates:
        year_counts[d[:4]] = year_counts.get(d[:4], 0) + 1

    return {
        "video_count": len(seen),
        "total_words": total_words,
        "earliest_published": dates[0] if dates else None,
        "latest_published": dates[-1] if dates else None,
        "median_published": dates[len(dates) // 2] if dates else None,
        "videos_by_year": dict(sorted(year_counts.items(), reverse=True)),
        "dated_video_count": len(dates),
        **temporal_service.summarize_eras(eras),
    }


def approved_document_ids_for_job(db: Any, job_id: str) -> list[str]:
    """The job's approved ``document_id`` set — what its Q&A retrieves from."""
    return [
        row[0]
        for row in db.query(JobVideo.document_id)
        .filter(JobVideo.job_id == job_id, JobVideo.approved.is_(True))
        .all()
        if row[0]
    ]


def corpus_statistics_for_job(db: Any, job_id: str) -> dict:
    """Statistics over a job's APPROVED documents — the set its Q&A retrieves from."""
    return corpus_statistics_for_document_ids(db, approved_document_ids_for_job(db, job_id))


def corpus_statistics_for_tenant(db: Any, tenant_id: str) -> dict:
    """Statistics over everything the tenant may see (D-063) — the library Q&A set."""
    from app.services import visibility_service

    ids = [row[0] for row in visibility_service.visible_document_ids(db, tenant_id).all()]
    return corpus_statistics_for_document_ids(db, ids)
