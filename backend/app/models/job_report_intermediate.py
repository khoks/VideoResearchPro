"""Report map/reduce intermediates per job run — S-1.14.6 (second half).

Why this exists: the report pipeline kept its per-batch map extractions and
its reduced dataset only in LangGraph state, so once compose ran nothing but
the final HTML survived. "What did the map phase extract, and what did reduce
drop?" could only be answered by replaying the job's inputs (D-055), and a
map regression stayed invisible until it was large enough to spoil the
finished report. The candidate-pool half of S-1.14.6 (`job_search_candidates`,
PR #205) closed the same gap for ranking; this closes it for map/reduce.

One row per map batch (bisected halves and failed batches included, so a
drop is visible as a row, not an absence) plus one row for the reduce
output. Rows are grouped by ``run_id`` so a re-run of the same job — a model
change, a prompt change — can be compared with the run before it.

Payloads are serialised at the moment each stage produces them. Compose
mutates item dicts afterwards (quote forms, modality tags); those mutations
must never leak into the audit record of what map and reduce emitted.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

STAGE_MAP = "map"
STAGE_REDUCE = "reduce"

# Map statuses: the batch returned parseable JSON / returned text that was
# not JSON (kept as {"raw": ...}, which reduce folds into facts) / the call
# failed and its chunks were dropped from the report.
MAP_PARSED = "parsed"
MAP_UNPARSED = "unparsed"
MAP_FAILED = "failed"
# Reduce statuses: everything fit (D-056 lossless union) / over the cost
# guard, compressed evenly per video.
REDUCE_LOSSLESS = "lossless"
REDUCE_COMPRESSED = "compressed"


class JobReportIntermediate(Base):
    __tablename__ = "job_report_intermediates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # One report-agent run. A job normally has one; regenerations add more.
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)

    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    # Map: the batch's position in map order. Reduce: 0.
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Map only: 0 / 1 when the batch failed and was bisected (S-1.12.6), else NULL.
    sub_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    # Map: transcript chunks the call covered. Reduce: NULL.
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Items across facts / comments / conclusions / references / speakers.
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Map: the parsed batch summary (or {"raw": ...}); NULL for a failed
    # batch. Reduce: the dataset compose received.
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Map: {"videos": [...], "error": "..."}. Reduce: the stage's processing
    # notes (duplicates collapsed, items trimmed, token totals).
    notes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The resolved model that produced the stage (reduce is code, not a model).
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_job_report_intermediates_job_run_stage", "job_id", "run_id", "stage"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<JobReportIntermediate {self.stage}#{self.batch_index} "
            f"{self.status} items={self.item_count} job={self.job_id[:8]}>"
        )
