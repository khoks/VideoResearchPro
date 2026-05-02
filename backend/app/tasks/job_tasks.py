import json
import logging
import sys
from datetime import datetime, timezone

from app.config import settings
from app.database import SessionLocal
from app.models.channel import Channel
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.transcript_cache import TranscriptCache
from app.models.document import Document
from app.services import chroma_service, progress_service, youtube_service
from app.sources import connector_for
from app.sources.types import Candidate, SourceMetadata
from app.tasks.celery_app import celery_app
from app.utils.chunking import chunk_transcript
from app.utils.html_builder import build_report_html, save_report

logger = logging.getLogger(__name__)


def _parse_published_at(value) -> datetime | None:
    """Coerce a YouTube `publishedAt` field into a datetime.

    YouTube returns ISO-8601 strings like `"2016-05-26T20:59:04Z"`. SQLAlchemy's
    SQLite DateTime column only accepts `datetime` objects, so we parse strings
    here and pass through anything already `datetime`-typed.
    """
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Python's fromisoformat handles trailing 'Z' from 3.11+.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            logger.warning("Could not parse published_at=%r; dropping", value)
            return None
    return None


def _channel_pending(db, channel_id: str) -> bool:
    """Is there already a Channel(channel_id=...) in this session's pending adds?

    ``db.get()`` only sees flushed rows, not objects in ``db.new``. When a
    single batch adds multiple videos that share a channel, the first call
    stages the Channel, the second call fails to see it, stages it again,
    and the commit then trips the UNIQUE constraint. Callers use this to
    dedup against in-session pending inserts.
    """
    return any(
        isinstance(obj, Channel) and obj.channel_id == channel_id
        for obj in db.new
    )


def _video_pending(db, video_id: str) -> bool:
    """Same idea as ``_channel_pending`` but for Document rows."""
    return any(
        isinstance(obj, Document) and obj.video_id == video_id
        for obj in db.new
    )


def _jobvideo_pending(db, job_id: str, video_id: str) -> bool:
    """Same idea as ``_channel_pending`` but for JobVideo link rows."""
    return any(
        isinstance(obj, JobVideo)
        and obj.job_id == job_id
        and obj.video_id == video_id
        for obj in db.new
    )


def _source_metadata_to_legacy_dict(sm: SourceMetadata) -> dict:
    """Convert a connector ``SourceMetadata`` back to the legacy
    ``youtube_service.get_video_details`` dict shape.

    The orchestrator now resolves video metadata via
    ``connector.fetch_metadata(...)`` rather than calling the YouTube
    service directly, but every downstream consumer in this module
    (``_upsert_video_and_link``, the channel-job duration filter,
    the subscription-job uploads-walk) still expects the flat dict
    shape. Bridging at the call-site boundary lets PR 3 ship without
    rewriting that downstream code; a future PR can promote callers
    to ``SourceMetadata`` directly now that the ``videos`` → ``documents``
    rename has landed.
    """
    return {
        "title": sm.title,
        "channel_id": sm.creator_external_id,
        "channel_name": sm.creator_name,
        "duration_seconds": sm.duration_seconds,
        "published_at": sm.published_at,
        "thumbnail_url": sm.thumbnail_url,
        "description": sm.description,
        "url": sm.extra.get("url"),
        "view_count": sm.extra.get("view_count"),
        "like_count": sm.extra.get("like_count"),
    }


def _upsert_video_and_link(db, job_id: str, data: dict) -> None:
    """Insert/refresh a global Document, its Channel, and the JobVideo link.

    `data` is the search-result dict from the Search Agent or YouTube service
    (keys: video_id, title, channel_id, channel_name, url, duration_seconds,
    thumbnail_url, description, selection_reason). Missing keys are tolerated.

    Existing Document rows are preserved with their transcript/embedding state;
    only lightweight surface metadata (title, thumbnail, url) is refreshed.

    E-1.10 note: Document PK is now ``document_id`` (UUID). Lookups by
    ``video_id`` go through the back-compat indexed column rather than
    ``Session.get()``. The JobVideo link's ``document_id`` is resolved
    explicitly here (rather than relying on the before_insert event)
    so we can also probe the in-flight session for unflushed pending
    inserts.
    """
    video_id = data.get("video_id") or ""
    if not video_id:
        return

    channel_id = data.get("channel_id") or None
    channel_name = data.get("channel_name") or ""

    # ``db.get()`` only checks already-flushed rows; it does NOT see
    # still-pending additions in ``db.new``. A search batch commonly
    # produces multiple videos from the same channel (e.g. 5 Firstpost
    # videos), so the first call adds the Channel, and the second call
    # does not see it yet and tries to add it again. That second insert
    # passes the in-memory check but then trips the UNIQUE constraint at
    # commit time, wedging the whole transaction. Check both layers.
    if channel_id and db.get(Channel, channel_id) is None and not _channel_pending(db, channel_id):
        db.add(Channel(channel_id=channel_id, name=channel_name or channel_id))

    # Document lookup via back-compat video_id column (PK is now document_id).
    video = db.query(Document).filter(Document.video_id == video_id).first()
    if video is None:
        # Not in the DB and not in db.new either — stage a new Document.
        if not _video_pending(db, video_id):
            video = Document(
                video_id=video_id,
                channel_id=channel_id,
                title=data.get("title", "Unknown"),
                url=data.get("url", f"https://www.youtube.com/watch?v={video_id}"),
                duration_seconds=data.get("duration_seconds", 0),
                published_at=_parse_published_at(data.get("published_at")),
                thumbnail_url=data.get("thumbnail_url"),
                description=data.get("description"),
            )
            db.add(video)
        else:
            # Already pending in this batch — find it in db.new for the
            # JobVideo link. _video_pending only checks; we need the
            # actual instance to grab document_id.
            video = next(
                (
                    obj
                    for obj in db.new
                    if isinstance(obj, Document) and obj.video_id == video_id
                ),
                None,
            )
    else:
        # Existing row: refresh lightweight surface metadata, preserve the rest.
        new_title = data.get("title")
        new_thumb = data.get("thumbnail_url")
        new_url = data.get("url")
        if new_title:
            video.title = new_title
        if new_thumb:
            video.thumbnail_url = new_thumb
        if new_url:
            video.url = new_url
        if channel_id and not video.channel_id:
            video.channel_id = channel_id

    if video is None:
        # Defensive — should not reach here, but if document staging
        # failed, skip the link rather than crash.
        return

    document_id = video.document_id

    # JobVideo lookup needs the new (job_id, document_id) PK; check both
    # the flushed table and the in-flight session.
    existing_link = db.get(JobVideo, (job_id, document_id))
    if existing_link is None and not _jobvideo_pending(db, job_id, video_id):
        db.add(JobVideo(
            job_id=job_id,
            document_id=document_id,
            video_id=video_id,
            approved=True,
            selection_reason=data.get("selection_reason"),
        ))


def _upsert_candidate_and_link(
    db,
    job_id: str,
    candidate,
    *,
    classification: dict | None = None,
    extracted_text=None,
) -> Document | None:
    """Insert/refresh a global Document from a connector ``Candidate`` and
    create the JobVideo (job_documents) link.

    Closes T-1.5.1.4 (Reddit storage) + T-1.5.2.5 (HN storage) + the
    persistence half of T-1.5.3.4 (classifier output → ``source_metadata``).

    Generalizes ``_upsert_video_and_link`` (which is YouTube-shaped and
    keyed on ``data["video_id"]``) to handle any ``source_type``. The
    canonical identity for non-video sources is ``(source_type, source_id)``;
    we resolve existing rows via the unique index on those two columns,
    not via the back-compat ``video_id`` column.

    Args:
        candidate: ``app.sources.types.Candidate``. Provides
            ``source_type`` (e.g. "reddit_post", "hn_story"),
            ``source_id`` (the platform-native ID, possibly already
            namespaced like "reddit:abc"), ``title``, ``source_url``,
            optional ``creator_external_id`` / ``creator_name`` / etc.
        classification: optional dict produced by
            ``social_classify.classify().model_dump()``; persisted onto
            ``Document.source_metadata_json["classification"]`` when
            present (T-1.5.3.4).
        extracted_text: optional ``ExtractedText`` from
            ``connector.fetch_text(...)``. When provided we record
            ``transcript_status='fetched'``, ``transcript_word_count``,
            ``transcript_language``, and ``transcript_source`` so the
            downstream chunk pipeline can be uniform across source types.

    Returns:
        The persisted ``Document`` (existing or newly added). ``None``
        only if the candidate has no ``source_id`` (a defensive guard).
    """
    import json

    source_type = candidate.source_type
    source_id = candidate.source_id
    if not source_id:
        return None

    # Resolve any existing Document by canonical (source_type, source_id) —
    # check both the flushed table AND db.new (in-flight inserts in the
    # same batch) so two upsert calls in one transaction collapse onto
    # one row.
    existing = (
        db.query(Document)
        .filter(
            Document.source_type == source_type,
            Document.source_id == source_id,
        )
        .first()
    )
    if existing is None:
        existing = next(
            (
                obj
                for obj in db.new
                if isinstance(obj, Document)
                and obj.source_type == source_type
                and obj.source_id == source_id
            ),
            None,
        )

    # Build / merge the source_metadata JSON. Classifier output (D-023)
    # lives under "classification"; future per-source extras can join
    # under their own keys (e.g. "reddit": {...} or "hn": {...}).
    metadata: dict = {}
    if existing is not None and existing.source_metadata_json:
        try:
            metadata = json.loads(existing.source_metadata_json) or {}
        except json.JSONDecodeError:
            metadata = {}
    if classification is not None:
        metadata["classification"] = classification

    if existing is not None:
        # Refresh lightweight surface metadata; preserve classification +
        # transcript state if they exist.
        if candidate.title:
            existing.title = candidate.title
        if candidate.source_url:
            existing.source_url = candidate.source_url
            if not existing.url:
                existing.url = candidate.source_url
        if candidate.thumbnail_url and not existing.thumbnail_url:
            existing.thumbnail_url = candidate.thumbnail_url
        if metadata:
            existing.source_metadata_json = json.dumps(metadata)
        if extracted_text is not None:
            existing.transcript_status = "fetched"
            existing.transcript_word_count = extracted_text.word_count
            existing.transcript_language = extracted_text.language
            existing.transcript_source = extracted_text.text_source
        document = existing
    else:
        # New row. video_id stays NULL for non-video sources; for
        # source_type='video' we mirror source_id into video_id so the
        # back-compat readers continue to find the row.
        video_id_for_compat = source_id if source_type == "video" else None
        document = Document(
            video_id=video_id_for_compat,
            source_type=source_type,
            source_id=source_id,
            source_url=candidate.source_url,
            title=candidate.title or "Untitled",
            url=candidate.source_url or "",
            thumbnail_url=candidate.thumbnail_url,
            description=candidate.description,
            duration_seconds=candidate.duration_seconds,
            published_at=candidate.published_at,
            channel_id=candidate.creator_external_id,
            source_metadata_json=json.dumps(metadata) if metadata else None,
            transcript_status=(
                "fetched" if extracted_text is not None else "pending"
            ),
            transcript_word_count=(
                extracted_text.word_count if extracted_text is not None else None
            ),
            transcript_language=(
                extracted_text.language if extracted_text is not None else None
            ),
            transcript_source=(
                extracted_text.text_source if extracted_text is not None else None
            ),
        )
        db.add(document)

    # Create the JobVideo link with the canonical document_id.
    existing_link = db.get(JobVideo, (job_id, document.document_id))
    if existing_link is None:
        db.add(
            JobVideo(
                job_id=job_id,
                document_id=document.document_id,
                # Mirror video_id into the back-compat column for video
                # rows; NULL for everything else.
                video_id=document.video_id,
                approved=True,
                selection_reason="topic_search",
            )
        )

    return document


def _resolve_source_types(job: Job) -> list[str]:
    """Decode ``Job.source_types_json`` into a Python list, defaulting
    to ``["video"]`` for back-compat with jobs created before the
    column existed (pre-2026-05-02)."""
    if not job.source_types_json:
        return ["video"]
    try:
        parsed = json.loads(job.source_types_json)
    except (TypeError, ValueError):
        logger.warning(
            "Job %s has malformed source_types_json %r; defaulting to ['video']",
            job.id,
            job.source_types_json,
        )
        return ["video"]
    if not isinstance(parsed, list) or not parsed:
        return ["video"]
    return [str(st) for st in parsed if str(st)]


def _dispatch_and_store_non_video_sources(
    db,
    job: Job,
    *,
    source_types: list[str],
    limit_per_type: int = 10,
) -> int:
    """For every non-video source_type on the job, run the dispatcher,
    fetch text inline (the connector classifies during fetch_text per
    [D-023](../../../docs/decisions.md#d-023)), and persist via
    ``_upsert_candidate_and_link``.

    Returns the total count of candidates stored across all non-video
    source types — the orchestrator combines this with the YouTube
    search-agent count for the user-visible "found N candidates"
    message.

    "Video" source_type is *not* handled here — the existing search
    agent (LangGraph) owns that path and produces a richer ranked
    output than `connector.search()` alone. This helper handles only
    the source_types where ``connector.search()`` is the canonical
    discovery surface (Reddit, HN, future Mastodon / Bluesky).
    """
    from app.services.connector_dispatch import dispatch_search

    non_video = [st for st in source_types if st != "video"]
    if not non_video:
        return 0

    logger.info(
        "[job:%s] Dispatching search for non-video source_types: %s",
        job.id,
        non_video,
    )

    result = dispatch_search(
        non_video,
        query=job.topic or "",
        instructions=job.search_instructions or "",
        limit_per_type=limit_per_type,
        job_id=job.id,
    )

    if result.has_errors:
        for st, err in result.errors_by_source_type.items():
            logger.warning(
                "[job:%s] dispatch_search error for source_type=%s: %s",
                job.id,
                st,
                err,
            )

    # For each candidate, run fetch_text (which classifies inline per
    # D-023) and persist. Failures on individual candidates are logged
    # and skipped — one bad post must not crash the job.
    from app.sources.registry import connector_for

    stored = 0
    for st, candidates in result.candidates_by_source_type.items():
        connector = connector_for(st)
        for cand in candidates:
            try:
                extracted = connector.fetch_text(
                    cand,
                    job_id=job.id,
                    query=job.topic or "",
                )
            except Exception:
                logger.exception(
                    "[job:%s] fetch_text failed for %s/%s",
                    job.id,
                    st,
                    cand.source_id,
                )
                extracted = None

            classification = None
            if extracted is not None and "classification" in extracted.extra:
                classification = extracted.extra["classification"]

            try:
                _upsert_candidate_and_link(
                    db,
                    job.id,
                    cand,
                    classification=classification,
                    extracted_text=extracted,
                )
                stored += 1
            except Exception:
                logger.exception(
                    "[job:%s] persist failed for %s/%s",
                    job.id,
                    st,
                    cand.source_id,
                )

    db.commit()
    logger.info(
        "[job:%s] Non-video dispatch persisted %d candidates across %d source types",
        job.id,
        stored,
        len(non_video),
    )
    return stored


def _build_video_metadata(video: Document, language: str | None) -> dict:
    """Build the metadata dict passed to ``chunk_transcript`` for a Document row."""
    return {
        "video_id": video.video_id,
        "title": video.title,
        "channel_name": video.channel_name,
        "channel_id": video.channel_id,
        "url": video.url,
        "published_at": video.published_at,
        "duration_seconds": video.duration_seconds,
        "language": language or getattr(video, "transcript_language", None) or "en",
    }


def _load_cached_segments(video_id: str) -> tuple[list[dict], str] | None:
    """Load cached transcript segments for ``video_id`` from TranscriptCache.

    Returns (segments, language) on hit, or None on miss / corrupt row.
    """
    db = SessionLocal()
    try:
        row = db.query(TranscriptCache).filter(TranscriptCache.video_id == video_id).first()
        if row is None:
            return None
        try:
            segments = json.loads(row.segments_json)
        except (ValueError, TypeError):
            logger.exception(
                "Corrupt transcript cache row for %s; ignoring", video_id
            )
            return None
        return segments, row.language
    finally:
        db.close()


def _get_job(db, job_id: str) -> Job | None:
    return db.query(Job).filter(Job.id == job_id).first()


def _update_job(db, job: Job, **kwargs) -> None:
    for key, value in kwargs.items():
        setattr(job, key, value)
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)


def _is_cancelled(db, job_id: str) -> bool:
    db.expire_all()
    job = _get_job(db, job_id)
    return job is not None and job.status == "cancelled"


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def execute_topic_job(self, job_id: str) -> None:
    """Orchestrates topic-based job Phase 1: search for videos."""
    db = SessionLocal()
    try:
        job = _get_job(db, job_id)
        if not job:
            logger.warning(f"[job:{job_id}] Job not found in DB, aborting")
            return

        logger.info(f"[job:{job_id}] Topic job starting: topic='{job.topic}', num_videos={job.num_videos}")

        _update_job(db, job, status="searching", progress_pct=5,
                    progress_message="Searching for relevant videos...", celery_task_id=self.request.id)
        progress_service.publish_status_change(job_id, "pending", "searching",
                                               "Searching for relevant videos...")

        if _is_cancelled(db, job_id):
            logger.info(f"[job:{job_id}] Job cancelled before search, exiting")
            return

        # Decode source_types — controls which connectors fan out for
        # discovery. Per S-1.5.11, video uses the LangGraph search agent
        # (richer ranking); non-video uses the connector_dispatch path.
        source_types = _resolve_source_types(job)
        wants_video = "video" in source_types

        curated_videos: list[dict] = []
        queries_used: list[str] = []

        # YouTube path (only when video is requested).
        if wants_video:
            from app.agents.search_agent import run_search_agent

            logger.info(
                f"[job:{job_id}] Starting Search Agent for topic: '{job.topic}'"
            )
            curated_videos, queries_used = run_search_agent(
                topic=job.topic,
                num_videos=job.num_videos,
                search_instructions=job.search_instructions or "",
                min_duration=job.min_duration_minutes,
                max_duration=job.max_duration_minutes,
                channel_type_filters=(
                    json.loads(job.channel_type_filters)
                    if job.channel_type_filters
                    else []
                ),
                preferred_channels=(
                    json.loads(job.preferred_channels)
                    if job.preferred_channels
                    else []
                ),
            )
            logger.info(
                f"[job:{job_id}] Search Agent complete: found "
                f"{len(curated_videos)} candidate videos"
            )

            if queries_used:
                job.search_queries_used = json.dumps(queries_used)
                db.commit()

        progress_service.publish_progress(
            job_id,
            "searching",
            15,
            f"Found {len(curated_videos)} videos. Fetching details...",
        )

        # Save YouTube videos to the global library and link to this job.
        for v in curated_videos:
            _upsert_video_and_link(db, job_id, v)
        db.commit()
        logger.info(
            f"[job:{job_id}] {len(curated_videos)} videos saved to DB"
        )

        # Non-video path: dispatch the configured social/etc connectors,
        # fetch text inline (which classifies per D-023), persist via
        # the source-type-agnostic helper.
        non_video_count = _dispatch_and_store_non_video_sources(
            db,
            job,
            source_types=source_types,
            limit_per_type=job.num_videos or 10,
        )

        total_candidates = len(curated_videos) + non_video_count
        logger.info(
            f"[job:{job_id}] Total candidates across all source_types: "
            f"{total_candidates} (video={len(curated_videos)}, "
            f"non_video={non_video_count})"
        )

        # Fail clearly if every source returned nothing — pushing the user to
        # the approval screen with an empty list is a dead end.
        if total_candidates == 0:
            msg = (
                f"No candidates found for topic '{job.topic}' across "
                f"source_types={source_types}. Try a broader topic, "
                "different search instructions, or relax the duration filters."
            )
            logger.warning(f"[job:{job_id}] {msg}")
            _handle_failure(db, job_id, msg)
            return

        _update_job(
            db, job, status="awaiting_approval", progress_pct=20,
            progress_message=f"Found {total_candidates} candidates. Please review and approve.",
        )
        progress_service.publish_status_change(
            job_id, "searching", "awaiting_approval",
            f"Found {total_candidates} candidates. Please review and approve.",
        )

    except Exception as e:
        logger.exception(f"[job:{job_id}] Topic job failed during search: {e}")
        _handle_failure(db, job_id, str(e))
    finally:
        # Backstop: if the task is about to return while the job is still
        # in a transient state, something silently bailed. Force-fail it so
        # the UI doesn't hang forever at "Searching...". Harmless when the
        # happy path already moved status to awaiting_approval/failed/etc.
        _backstop_orphan(db, job_id)
        db.close()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def execute_channel_job(self, job_id: str) -> None:
    """Orchestrates channel-based job Phase 1: fetch videos from channels."""
    db = SessionLocal()
    try:
        job = _get_job(db, job_id)
        if not job:
            logger.warning(f"[job:{job_id}] Job not found in DB, aborting")
            return

        channel_list = json.loads(job.channel_list) if job.channel_list else []
        videos_per_channel = job.videos_per_channel or 10
        logger.info(f"[job:{job_id}] Channel job starting: {len(channel_list)} channels, "
                    f"{videos_per_channel} videos/channel")

        _update_job(db, job, status="searching", progress_pct=5,
                    progress_message="Fetching videos from channels...", celery_task_id=self.request.id)
        progress_service.publish_status_change(job_id, "pending", "searching",
                                               "Fetching videos from channels...")

        if _is_cancelled(db, job_id):
            logger.info(f"[job:{job_id}] Job cancelled before channel fetch, exiting")
            return

        all_video_ids = []
        connector = connector_for("video")

        for i, channel_input in enumerate(channel_list):
            if _is_cancelled(db, job_id):
                logger.info(f"[job:{job_id}] Job cancelled mid-channel-fetch, exiting")
                return

            progress_service.publish_progress(
                job_id, "searching", 5 + int(10 * (i / len(channel_list))),
                f"Processing channel {i + 1}/{len(channel_list)}: {channel_input}"
            )

            # Resolve channel ID
            logger.info(f"[job:{job_id}] Channel {i + 1}/{len(channel_list)}: resolving '{channel_input}'")
            channel_id = connector.resolve_creator_id(channel_input, job_id=job_id)
            if not channel_id:
                logger.warning(f"[job:{job_id}] Could not resolve channel: '{channel_input}', skipping")
                continue

            logger.info(f"[job:{job_id}] Channel '{channel_input}' → {channel_id}, "
                        f"fetching up to {videos_per_channel} videos")

            # Fetch candidate items from the channel; we only need the IDs
            # here because metadata enrichment happens below.
            video_ids = [
                c.source_id
                for c in connector.list_creator_items(
                    channel_id, limit=videos_per_channel, job_id=job_id
                )
            ]
            logger.info(f"[job:{job_id}] Fetched {len(video_ids)} video IDs from channel {channel_id}")
            all_video_ids.extend(video_ids)

        logger.info(f"[job:{job_id}] All channels processed: {len(all_video_ids)} total video IDs before filtering")

        # Fetch details for all videos
        accepted_count = 0
        if all_video_ids:
            details_meta = connector.fetch_metadata(all_video_ids, job_id=job_id)
            details = {
                vid: _source_metadata_to_legacy_dict(sm)
                for vid, sm in details_meta.items()
            }

            # Apply duration filters
            for vid, info in details.items():
                dur_min = info.get("duration_seconds", 0) / 60
                if job.min_duration_minutes and dur_min < job.min_duration_minutes:
                    continue
                if job.max_duration_minutes and dur_min > job.max_duration_minutes:
                    continue

                _upsert_video_and_link(db, job_id, {"video_id": vid, **info})
                accepted_count += 1
            db.commit()

        logger.info(f"[job:{job_id}] Duration filter applied: {accepted_count}/{len(all_video_ids)} videos accepted")

        video_count = len(job.videos)
        logger.info(f"[job:{job_id}] {video_count} videos saved to DB, awaiting user approval")

        # Fail clearly when zero channels resolved or zero videos passed filters.
        # Going to awaiting_approval with an empty list traps the user with no
        # approval action they can take.
        if video_count == 0:
            if not all_video_ids:
                msg = (
                    f"None of the {len(channel_list)} channel(s) could be resolved. "
                    "Check the channel URLs/handles and try again."
                )
            else:
                msg = (
                    f"All {len(all_video_ids)} videos were excluded by the duration filters "
                    f"(min={job.min_duration_minutes}, max={job.max_duration_minutes} minutes). "
                    "Loosen the filters and try again."
                )
            logger.warning(f"[job:{job_id}] No videos available; failing job: {msg}")
            _handle_failure(db, job_id, msg)
            return

        _update_job(db, job, status="awaiting_approval", progress_pct=20,
                    progress_message=f"Found {video_count} videos. Please review and approve.")
        progress_service.publish_status_change(job_id, "searching", "awaiting_approval",
                                               f"Found {video_count} videos. Please review and approve.")

    except Exception as e:
        logger.exception(f"[job:{job_id}] Channel job failed during search: {e}")
        _handle_failure(db, job_id, str(e))
    finally:
        _backstop_orphan(db, job_id)
        db.close()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def resume_job_after_approval(self, job_id: str) -> None:
    """Resumes job after user approves video list: extract → RAG → report → done."""
    db = SessionLocal()
    try:
        job = _get_job(db, job_id)
        if not job:
            logger.warning(f"[job:{job_id}] Job not found in DB, aborting")
            return

        # PHASE: EXTRACTING
        # `approved` now lives on the JobVideo link row, not on Document.
        approved_rows = (
            db.query(Document)
            .join(JobVideo, JobVideo.video_id == Document.video_id)
            .filter(JobVideo.job_id == job_id, JobVideo.approved.is_(True))
            .all()
        )
        approved_videos = approved_rows
        total = len(approved_videos)
        logger.info(f"[job:{job_id}] Resuming job after approval: {total} approved videos "
                    f"to process (job_type={job.job_type})")

        _update_job(db, job, status="extracting", progress_pct=30,
                    progress_message=f"Extracting transcripts (0/{total})...",
                    celery_task_id=self.request.id)
        progress_service.publish_status_change(job_id, "awaiting_approval", "extracting",
                                               f"Extracting transcripts for {total} videos...")

        all_chunks: list[dict] = []
        new_chunks: list[dict] = []
        fetched_count = 0
        reused_count = 0
        newly_processed_count = 0

        global_collection_name = getattr(
            settings, "CHROMA_GLOBAL_COLLECTION_NAME", "pratidhvani_global"
        )

        for i, video in enumerate(approved_videos):
            if _is_cancelled(db, job_id):
                logger.info(f"[job:{job_id}] Job cancelled during extraction at video {i + 1}/{total}, exiting")
                return

            title_preview = (video.title or "")[:60]
            already_fetched = video.transcript_status == "fetched"
            already_embedded = bool(getattr(video, "embedded_in_chroma", False))

            # Fully reused: re-chunk from the transcript cache so the report
            # agent still sees this video's content, but skip fetch + Chroma
            # insert. JobVideo link is assumed to already exist.
            if already_fetched and already_embedded:
                cached = _load_cached_segments(video.video_id)
                if cached is not None:
                    segments, cached_language = cached
                    chunks = chunk_transcript(
                        segments,
                        chunk_size=settings.CHUNK_SIZE,
                        chunk_overlap=settings.CHUNK_OVERLAP,
                        video_metadata=_build_video_metadata(video, cached_language),
                    )
                    all_chunks.extend(chunks)
                    reused_count += 1
                    fetched_count += 1
                    logger.info(
                        f"[job:{job_id}] [{i + 1}/{total}] Reusing library video "
                        f"(already embedded): video_id={video.video_id} '{title_preview}' "
                        f"→ {len(chunks)} chunks"
                    )
                else:
                    # Inconsistent state: flag says embedded, but no cached
                    # transcript to re-chunk. Fall through to a full fetch.
                    logger.warning(
                        f"[job:{job_id}] [{i + 1}/{total}] video_id={video.video_id} "
                        "is marked embedded but transcript cache is missing; re-fetching"
                    )
                    already_fetched = False
                    already_embedded = False

            # Previously fetched but never embedded (e.g. subscription ingest
            # saved the transcript without building the RAG). Embed it now.
            if already_fetched and not already_embedded:
                cached = _load_cached_segments(video.video_id)
                if cached is not None:
                    segments, cached_language = cached
                    chunks = chunk_transcript(
                        segments,
                        chunk_size=settings.CHUNK_SIZE,
                        chunk_overlap=settings.CHUNK_OVERLAP,
                        video_metadata=_build_video_metadata(video, cached_language),
                    )
                    all_chunks.extend(chunks)
                    new_chunks.extend(chunks)
                    if hasattr(video, "embedded_in_chroma"):
                        video.embedded_in_chroma = True
                    db.commit()
                    newly_processed_count += 1
                    fetched_count += 1
                    logger.info(
                        f"[job:{job_id}] [{i + 1}/{total}] Embedding cached transcript: "
                        f"video_id={video.video_id} '{title_preview}' → {len(chunks)} chunks"
                    )
                else:
                    logger.warning(
                        f"[job:{job_id}] [{i + 1}/{total}] video_id={video.video_id} "
                        "is marked fetched but transcript cache is missing; re-fetching"
                    )
                    already_fetched = False

            # Never fetched: full fetch + chunk + embed + update Document row.
            if not already_fetched:
                logger.info(
                    f"[job:{job_id}] [{i + 1}/{total}] Fetching transcript: "
                    f"video_id={video.video_id} '{title_preview}'"
                )
                connector = connector_for(video.source_type)
                extracted = connector.fetch_text(
                    Candidate(
                        source_type=video.source_type,
                        source_id=video.source_id,
                        title=video.title,
                        source_url=video.source_url or video.url,
                    ),
                    job_id=job_id,
                    query=job.topic or "",
                )

                if extracted:
                    transcript = extracted.segments
                    actual_language = extracted.language
                    word_count = extracted.word_count

                    video.transcript_status = "fetched"
                    video.transcript_word_count = word_count
                    video.transcript_language = actual_language
                    # Optional columns added by Unit 1's migration. Set when
                    # present; silently skipped on older schemas.
                    if hasattr(video, "transcripted_at"):
                        video.transcripted_at = datetime.now(timezone.utc)
                    if hasattr(video, "transcript_source"):
                        video.transcript_source = extracted.text_source

                    chunks = chunk_transcript(
                        transcript,
                        chunk_size=settings.CHUNK_SIZE,
                        chunk_overlap=settings.CHUNK_OVERLAP,
                        video_metadata=_build_video_metadata(video, actual_language),
                    )
                    all_chunks.extend(chunks)
                    new_chunks.extend(chunks)

                    if hasattr(video, "embedded_in_chroma"):
                        video.embedded_in_chroma = True

                    newly_processed_count += 1
                    fetched_count += 1
                    logger.info(
                        f"[job:{job_id}] [{i + 1}/{total}] Transcript OK: "
                        f"{word_count} words → {len(chunks)} chunks (video_id={video.video_id})"
                    )
                else:
                    video.transcript_status = "unavailable"
                    logger.warning(
                        f"[job:{job_id}] [{i + 1}/{total}] Transcript unavailable: "
                        f"video_id={video.video_id} '{title_preview}'"
                    )

                db.commit()

            progress_pct = 30 + int(25 * ((i + 1) / total))
            attempted = i + 1
            unavailable_so_far = attempted - fetched_count
            progress_message = (
                f"Video {attempted}/{total}: "
                f"{fetched_count} fetched, {unavailable_so_far} unavailable "
                f"(reused {reused_count}, new {newly_processed_count})..."
            )
            progress_service.publish_progress(
                job_id, "extracting", progress_pct, progress_message,
                data={
                    "transcripts_fetched": fetched_count,
                    "transcripts_attempted": attempted,
                    "transcripts_total": total,
                    "transcripts_unavailable": unavailable_so_far,
                    "reused_count": reused_count,
                    "newly_processed_count": newly_processed_count,
                },
            )
            # Also persist to the DB so page reloads (or clients that aren't
            # WS-connected) see the current state, not the stale initial
            # "Extracting transcripts (0/N)..." message. Showing attempted +
            # fetched (not just fetched) means the counter advances even when
            # every video is falling through to a failing Whisper fallback —
            # otherwise it looks frozen.
            job.progress_pct = progress_pct
            job.progress_message = progress_message
            job.updated_at = datetime.now(timezone.utc)
            db.commit()

        unavailable_count = total - fetched_count
        logger.info(
            f"[job:{job_id}] Extraction complete: {fetched_count} fetched "
            f"(reused={reused_count}, new={newly_processed_count}), "
            f"{unavailable_count} unavailable, {len(all_chunks)} total chunks"
        )

        if fetched_count == 0:
            logger.error(f"[job:{job_id}] No transcripts fetched for any of {total} videos, failing job")
            _update_job(db, job, status="failed",
                        error_message="No transcripts could be fetched for any video.")
            progress_service.publish_error(job_id, "No transcripts available.")
            return

        # PHASE: BUILDING_RAG
        if _is_cancelled(db, job_id):
            logger.info(f"[job:{job_id}] Job cancelled before RAG build, exiting")
            return

        _update_job(db, job, status="building_rag", progress_pct=60,
                    progress_message="Building knowledge base...")
        progress_service.publish_status_change(job_id, "extracting", "building_rag",
                                               "Building knowledge base...")

        logger.info(
            f"[job:{job_id}] Building RAG: inserting {len(new_chunks)} new chunks "
            f"into global ChromaDB collection '{global_collection_name}' "
            f"(skipped {len(all_chunks) - len(new_chunks)} already-embedded chunks)"
        )
        if new_chunks:
            chroma_service.insert_chunks(new_chunks)
        _update_job(db, job, chroma_collection_name=global_collection_name)
        logger.info(
            f"[job:{job_id}] RAG built: {len(new_chunks)} new chunks indexed in "
            f"'{global_collection_name}' (total for this job: {len(all_chunks)})"
        )

        progress_service.publish_progress(
            job_id, "building_rag", 70,
            f"Indexed {len(new_chunks)} new chunks into the library "
            f"({len(all_chunks)} total for this job).",
            data={
                "reused_count": reused_count,
                "newly_processed_count": newly_processed_count,
                "new_chunks": len(new_chunks),
                "total_chunks": len(all_chunks),
            },
        )

        # PHASE: GENERATING_REPORT
        if _is_cancelled(db, job_id):
            logger.info(f"[job:{job_id}] Job cancelled before report generation, exiting")
            return

        _update_job(db, job, status="generating_report", progress_pct=80,
                    progress_message="Generating report...")
        progress_service.publish_status_change(job_id, "building_rag", "generating_report",
                                               "Generating report...")

        from app.agents.report_agent import run_report_agent
        logger.info(f"[job:{job_id}] Generating report (job_type={job.job_type}, "
                    f"videos={fetched_count}, chunks={len(all_chunks)})")
        statistics, report_body = run_report_agent(
            job_type=job.job_type,
            topic=job.topic or "Channel Collection",
            transcript_chunks=all_chunks,
        )
        logger.info(f"[job:{job_id}] Report agent complete, building HTML...")

        # Build and save HTML report
        title = f"Research Report: {job.topic}" if job.job_type == "topic" else "Channel Collection Report"
        html = build_report_html(
            title=title,
            job_type=job.job_type,
            statistics=statistics,
            report_body=report_body,
        )
        report_path = save_report(job_id, html)
        logger.info(f"[job:{job_id}] Report saved to '{report_path}'")

        # PHASE: COMPLETED
        _update_job(db, job, status="completed", progress_pct=100,
                    progress_message="Job completed successfully!",
                    report_path=report_path,
                    completed_at=datetime.now(timezone.utc))
        progress_service.publish_status_change(job_id, "generating_report", "completed",
                                               "Job completed successfully!")
        logger.info(f"[job:{job_id}] Job COMPLETED: fetched={fetched_count}, "
                    f"unavailable={unavailable_count}, chunks={len(all_chunks)}, report='{report_path}'")

    except Exception as e:
        logger.exception(f"[job:{job_id}] Job failed: {e}")
        _handle_failure(db, job_id, str(e))
    finally:
        _backstop_orphan(db, job_id)
        db.close()


def _run_extraction_and_rag(self, db, job) -> None:
    """Fetch transcripts for approved videos, chunk, and index them in ChromaDB.

    Stops short of report generation — subscription jobs skip the report phase.
    Shared between ``resume_job_after_approval`` semantics and subscription
    ingest.
    """
    job_id = job.id
    # `approved` now lives on the JobVideo link row, not on Document.
    approved_videos = (
        db.query(Document)
        .join(JobVideo, JobVideo.video_id == Document.video_id)
        .filter(JobVideo.job_id == job_id, JobVideo.approved.is_(True))
        .all()
    )
    total = len(approved_videos)
    logger.info(
        f"[job:{job_id}] Starting extraction+RAG for {total} approved video(s) "
        f"(job_type={job.job_type})"
    )

    _update_job(
        db, job,
        status="extracting",
        progress_pct=30,
        progress_message=f"Extracting transcripts (0/{total})...",
        celery_task_id=self.request.id,
    )
    progress_service.publish_status_change(
        job_id, job.status, "extracting",
        f"Extracting transcripts for {total} videos...",
    )

    all_chunks: list[dict] = []
    new_chunks: list[dict] = []
    fetched_count = 0
    reused_count = 0
    newly_processed_count = 0

    global_collection_name = getattr(
        settings, "CHROMA_GLOBAL_COLLECTION_NAME", "pratidhvani_global"
    )

    for i, video in enumerate(approved_videos):
        if _is_cancelled(db, job_id):
            logger.info(
                f"[job:{job_id}] Job cancelled during extraction at video {i + 1}/{total}, exiting"
            )
            return

        title_preview = (video.title or "")[:60]
        already_fetched = video.transcript_status == "fetched"
        already_embedded = bool(getattr(video, "embedded_in_chroma", False))

        # Fully reused: re-chunk from the transcript cache without fetch/embed.
        if already_fetched and already_embedded:
            cached = _load_cached_segments(video.video_id)
            if cached is not None:
                segments, cached_language = cached
                chunks = chunk_transcript(
                    segments,
                    chunk_size=settings.CHUNK_SIZE,
                    chunk_overlap=settings.CHUNK_OVERLAP,
                    video_metadata=_build_video_metadata(video, cached_language),
                )
                all_chunks.extend(chunks)
                reused_count += 1
                fetched_count += 1
                logger.info(
                    f"[job:{job_id}] [{i + 1}/{total}] Reusing library video: "
                    f"video_id={video.video_id} '{title_preview}' -> {len(chunks)} chunks"
                )
            else:
                already_fetched = False
                already_embedded = False

        if already_fetched and not already_embedded:
            cached = _load_cached_segments(video.video_id)
            if cached is not None:
                segments, cached_language = cached
                chunks = chunk_transcript(
                    segments,
                    chunk_size=settings.CHUNK_SIZE,
                    chunk_overlap=settings.CHUNK_OVERLAP,
                    video_metadata=_build_video_metadata(video, cached_language),
                )
                all_chunks.extend(chunks)
                new_chunks.extend(chunks)
                if hasattr(video, "embedded_in_chroma"):
                    video.embedded_in_chroma = True
                db.commit()
                newly_processed_count += 1
                fetched_count += 1
                logger.info(
                    f"[job:{job_id}] [{i + 1}/{total}] Embedding cached transcript: "
                    f"video_id={video.video_id} '{title_preview}' -> {len(chunks)} chunks"
                )
            else:
                already_fetched = False

        if not already_fetched:
            logger.info(
                f"[job:{job_id}] [{i + 1}/{total}] Fetching transcript: "
                f"video_id={video.video_id} '{title_preview}'"
            )
            connector = connector_for(video.source_type)
            extracted = connector.fetch_text(
                Candidate(
                    source_type=video.source_type,
                    source_id=video.source_id,
                    title=video.title,
                    source_url=video.source_url or video.url,
                ),
                job_id=job_id,
                query=job.topic or "",
            )

            if extracted:
                transcript = extracted.segments
                actual_language = extracted.language
                word_count = extracted.word_count

                video.transcript_status = "fetched"
                video.transcript_word_count = word_count
                video.transcript_language = actual_language
                if hasattr(video, "transcripted_at"):
                    video.transcripted_at = datetime.now(timezone.utc)
                if hasattr(video, "transcript_source"):
                    video.transcript_source = extracted.text_source

                chunks = chunk_transcript(
                    transcript,
                    chunk_size=settings.CHUNK_SIZE,
                    chunk_overlap=settings.CHUNK_OVERLAP,
                    video_metadata=_build_video_metadata(video, actual_language),
                )
                all_chunks.extend(chunks)
                new_chunks.extend(chunks)

                if hasattr(video, "embedded_in_chroma"):
                    video.embedded_in_chroma = True

                newly_processed_count += 1
                fetched_count += 1
                logger.info(
                    f"[job:{job_id}] [{i + 1}/{total}] Transcript OK: "
                    f"{word_count} words -> {len(chunks)} chunks (video_id={video.video_id})"
                )
            else:
                video.transcript_status = "unavailable"
                logger.warning(
                    f"[job:{job_id}] [{i + 1}/{total}] Transcript unavailable: "
                    f"video_id={video.video_id} '{title_preview}'"
                )

            db.commit()

        progress_pct = 30 + int(25 * ((i + 1) / total)) if total else 55
        attempted = i + 1
        unavailable_so_far = attempted - fetched_count
        progress_message = (
            f"Video {attempted}/{total}: "
            f"{fetched_count} fetched, {unavailable_so_far} unavailable "
            f"(reused {reused_count}, new {newly_processed_count})..."
        )
        progress_service.publish_progress(
            job_id, "extracting", progress_pct, progress_message,
            data={
                "transcripts_fetched": fetched_count,
                "transcripts_attempted": attempted,
                "transcripts_total": total,
                "transcripts_unavailable": unavailable_so_far,
                "reused_count": reused_count,
                "newly_processed_count": newly_processed_count,
            },
        )
        # Persist to the DB so reloads don't see the stale initial message.
        job.progress_pct = progress_pct
        job.progress_message = progress_message
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

    unavailable_count = total - fetched_count
    logger.info(
        f"[job:{job_id}] Extraction complete: {fetched_count} fetched "
        f"(reused={reused_count}, new={newly_processed_count}), "
        f"{unavailable_count} unavailable, {len(all_chunks)} total chunks"
    )

    if fetched_count == 0:
        logger.error(
            f"[job:{job_id}] No transcripts fetched for any of {total} videos, failing job"
        )
        _update_job(
            db, job,
            status="failed",
            error_message="No transcripts could be fetched for any video.",
        )
        progress_service.publish_error(job_id, "No transcripts available.")
        return

    if _is_cancelled(db, job_id):
        logger.info(f"[job:{job_id}] Job cancelled before RAG build, exiting")
        return

    _update_job(
        db, job,
        status="building_rag",
        progress_pct=60,
        progress_message="Building knowledge base...",
    )
    progress_service.publish_status_change(
        job_id, "extracting", "building_rag", "Building knowledge base..."
    )

    logger.info(
        f"[job:{job_id}] Building RAG: inserting {len(new_chunks)} new chunks "
        f"into global ChromaDB collection '{global_collection_name}' "
        f"(skipped {len(all_chunks) - len(new_chunks)} already-embedded chunks)"
    )
    if new_chunks:
        chroma_service.insert_chunks(new_chunks)
    _update_job(db, job, chroma_collection_name=global_collection_name)
    logger.info(
        f"[job:{job_id}] RAG built: {len(new_chunks)} new chunks indexed in "
        f"'{global_collection_name}' (total for this job: {len(all_chunks)})"
    )

    progress_service.publish_progress(
        job_id, "building_rag", 70,
        f"Indexed {len(new_chunks)} new chunks into the library "
        f"({len(all_chunks)} total for this job).",
        data={
            "reused_count": reused_count,
            "newly_processed_count": newly_processed_count,
            "new_chunks": len(new_chunks),
            "total_chunks": len(all_chunks),
        },
    )


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def execute_subscription_job(self, job_id: str) -> None:
    """Fire-and-forget subscription ingest: resolve channels, walk uploads, extract, embed.

    Skips the approval pause and the report phase. Channels are upserted into
    the global ``channels`` table and marked ``subscribed=True``. All uploads
    are ingested as approved videos so the existing extraction pipeline runs
    untouched.
    """
    db = SessionLocal()
    try:
        job = _get_job(db, job_id)
        if not job:
            logger.warning(f"[job:{job_id}] Job not found in DB, aborting")
            return

        channel_inputs = json.loads(job.channel_list) if job.channel_list else []
        logger.info(
            f"[job:{job_id}] Subscription job starting: {len(channel_inputs)} channel input(s)"
        )

        _update_job(
            db, job,
            status="searching",
            progress_pct=5,
            progress_message="Resolving channels...",
            celery_task_id=self.request.id,
        )
        progress_service.publish_status_change(
            job_id, "pending", "searching", "Resolving channels..."
        )

        if _is_cancelled(db, job_id):
            logger.info(f"[job:{job_id}] Job cancelled before channel resolve, exiting")
            return

        resolved_channels: list[dict] = []
        connector = connector_for("video")

        # Phase 1: resolve + upsert channels
        for i, channel_input in enumerate(channel_inputs):
            if _is_cancelled(db, job_id):
                logger.info(f"[job:{job_id}] Job cancelled mid channel-resolve, exiting")
                return

            progress_service.publish_progress(
                job_id, "searching", 5 + int(10 * (i / max(1, len(channel_inputs)))),
                f"Resolving channel {i + 1}/{len(channel_inputs)}: {channel_input}",
            )

            channel_id = connector.resolve_creator_id(channel_input, job_id=job_id)
            if not channel_id:
                logger.warning(
                    f"[job:{job_id}] Could not resolve channel: '{channel_input}', skipping"
                )
                continue

            creator = connector.fetch_creator(channel_id, job_id=job_id)
            if not creator:
                logger.warning(
                    f"[job:{job_id}] Could not fetch metadata for channel {channel_id}, skipping"
                )
                continue
            uploads_playlist_id = creator.extra.get("uploads_playlist_id")

            channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
            if channel is None:
                channel = Channel(
                    channel_id=channel_id,
                    name=creator.name or "",
                    uploads_playlist_id=uploads_playlist_id,
                    subscriber_count=creator.subscriber_count,
                    subscribed=True,
                )
                db.add(channel)
            else:
                if creator.name:
                    channel.name = creator.name
                if uploads_playlist_id:
                    channel.uploads_playlist_id = uploads_playlist_id
                if creator.subscriber_count is not None:
                    channel.subscriber_count = creator.subscriber_count
                channel.subscribed = True
            db.commit()

            resolved_channels.append({
                "channel_id": channel_id,
                "name": channel.name,
                "uploads_playlist_id": channel.uploads_playlist_id,
            })

        if not resolved_channels:
            msg = (
                f"None of the {len(channel_inputs)} channel(s) could be resolved. "
                "Check the channel URLs/handles and try again."
            )
            logger.warning(f"[job:{job_id}] {msg}")
            _handle_failure(db, job_id, msg)
            return

        # channel_list_resolved stores the user-facing summary only;
        # the uploads_playlist_id stays on the Channel row.
        job.channel_list_resolved = json.dumps(
            [{"channel_id": c["channel_id"], "name": c["name"]} for c in resolved_channels]
        )
        db.commit()

        # Phase 2: walk uploads, fetch details, insert Document rows
        if _is_cancelled(db, job_id):
            logger.info(f"[job:{job_id}] Job cancelled before uploads walk, exiting")
            return

        progress_service.publish_progress(
            job_id, "searching", 18,
            f"Resolved {len(resolved_channels)} channel(s). Walking uploads...",
        )

        # Videos already linked to this job from prior partial runs.
        linked_video_ids = {
            jv.video_id for jv in db.query(JobVideo.video_id).filter(JobVideo.job_id == job_id).all()
        }
        total_ingested = 0

        for i, entry in enumerate(resolved_channels):
            if _is_cancelled(db, job_id):
                logger.info(f"[job:{job_id}] Job cancelled mid uploads walk, exiting")
                return

            channel_id = entry["channel_id"]
            name = entry["name"]
            progress_service.publish_progress(
                job_id, "searching", 18 + int(7 * (i / max(1, len(resolved_channels)))),
                f"Walking uploads for {name} ({i + 1}/{len(resolved_channels)})",
            )

            # Subscription jobs walk every page of the uploads playlist
            # and benefit from the cached `uploads_playlist_id` (saves one
            # `channels.list` quota unit per channel). The connector
            # contract has no per-source-type optimization slot today, so
            # this single seam stays on `youtube_service` until we extend
            # `list_creator_items` with an `extra` kwargs bag in a later PR.
            video_ids = youtube_service.get_channel_videos_all(
                channel_id,
                job_id=job_id,
                uploads_playlist_id=entry.get("uploads_playlist_id"),
            )
            unlinked_ids = [vid for vid in video_ids if vid not in linked_video_ids]
            logger.info(
                f"[job:{job_id}] Channel {channel_id}: {len(video_ids)} videos "
                f"({len(unlinked_ids)} to link to this job)"
            )

            if unlinked_ids:
                # Fetch details for videos not yet in the global library so we
                # populate Document rows with accurate metadata. _upsert_video_and_link
                # tolerates pre-existing Document rows and just creates the JobVideo.
                missing_from_library = [
                    vid for vid in unlinked_ids if db.get(Document, vid) is None
                ]
                details: dict = {}
                if missing_from_library:
                    details_meta = connector.fetch_metadata(
                        missing_from_library, job_id=job_id
                    )
                    details = {
                        vid: _source_metadata_to_legacy_dict(sm)
                        for vid, sm in details_meta.items()
                    }
                for vid in unlinked_ids:
                    info = details.get(vid) or {}
                    _upsert_video_and_link(db, job_id, {
                        "video_id": vid,
                        "title": info.get("title", "Unknown"),
                        "channel_id": info.get("channel_id", channel_id),
                        "channel_name": info.get("channel_name", name),
                        "url": info.get("url", f"https://www.youtube.com/watch?v={vid}"),
                        "duration_seconds": info.get("duration_seconds", 0),
                        "thumbnail_url": info.get("thumbnail_url"),
                        "published_at": info.get("published_at"),
                        "selection_reason": "subscription",
                    })
                    linked_video_ids.add(vid)
                    total_ingested += 1
                db.commit()

            # Update last_synced_at on the channel once all its uploads are staged.
            channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
            if channel is not None:
                channel.last_synced_at = datetime.now(timezone.utc)
                db.commit()

            progress_service.publish_progress(
                job_id, "searching", 18 + int(7 * ((i + 1) / max(1, len(resolved_channels)))),
                f"{total_ingested} videos ingested so far...",
            )

        logger.info(
            f"[job:{job_id}] Subscription uploads walk complete: "
            f"{total_ingested} new video(s) ingested"
        )

        db.refresh(job)
        if not job.videos:
            msg = "No videos were found in any subscribed channel."
            logger.warning(f"[job:{job_id}] {msg}")
            _handle_failure(db, job_id, msg)
            return

        # Phase 3: extraction + RAG (skip report).
        _run_extraction_and_rag(self, db, job)

        db.refresh(job)
        if job.status in ("failed", "cancelled"):
            return

        # Skip generating_report — subscription jobs produce no report.
        _update_job(
            db, job,
            status="completed",
            progress_pct=100,
            progress_message="Subscription sync completed successfully!",
            report_path=None,
            completed_at=datetime.now(timezone.utc),
        )
        progress_service.publish_status_change(
            job_id, "building_rag", "completed", "Subscription sync completed successfully!"
        )
        logger.info(f"[job:{job_id}] Subscription job COMPLETED")

    except Exception as e:
        logger.exception(f"[job:{job_id}] Subscription job failed: {e}")
        _handle_failure(db, job_id, str(e))
    finally:
        _backstop_orphan(db, job_id)
        db.close()


# States a task leaves behind only when it's actively mid-run. If a task is
# returning and the row is still in one of these, nobody's ever going to move
# it forward — force-fail so the UI doesn't wedge at "Searching...".
_TRANSIENT_STATUSES = {"pending", "searching", "extracting", "building_rag", "generating_report"}


def _backstop_orphan(db, job_id: str) -> None:
    """Force-fail a job whose task returned while still in a transient status.

    Called from the ``finally`` of every orchestrator task. If the happy path
    already moved status to ``awaiting_approval`` / ``completed`` / ``failed``
    / ``cancelled``, this is a silent no-op. Otherwise we set status=failed
    with a diagnostic message so the user isn't stranded watching a dead
    progress bar.

    Swallows its own exceptions — this is a last-resort safety net; it must
    never itself bring the task down.
    """
    try:
        fresh = SessionLocal()
        try:
            job = fresh.query(Job).filter(Job.id == job_id).first()
            if job is None or job.status not in _TRANSIENT_STATUSES:
                return
            stuck_in = job.status
            logger.error(
                f"[job:{job_id}] Orphan backstop tripped: task returned with status={stuck_in!r}; "
                "marking failed. Check worker logs for the root cause."
            )
            job.status = "failed"
            job.error_message = (
                f"Task returned without advancing from '{stuck_in}'. "
                "This usually means an exception fired inside the orchestrator "
                "but the failure handler did not record it. Retry the job; "
                "if it repeats, inspect the Celery worker logs."
            )
            job.progress_message = "Failed: orchestrator returned without recording a result."
            job.updated_at = datetime.now(timezone.utc)
            fresh.commit()
            try:
                from app.services import progress_service as _ps
                _ps.publish_error(job_id, job.error_message)
            except Exception:
                logger.exception(f"[job:{job_id}] backstop failed to publish progress error")
        finally:
            fresh.close()
    except Exception:
        logger.exception(f"[job:{job_id}] _backstop_orphan itself raised; swallowing")


def _handle_failure(db, job_id: str, error: str) -> None:
    """Set job to failed and publish error."""
    # Translate YouTube quota exhaustion into a user-friendly message.
    from app.services.quota_service import QuotaExceededError
    exc_type, exc_value, _ = sys.exc_info()
    if exc_type is not None and issubclass(exc_type, QuotaExceededError):
        error = (
            "YouTube API daily quota exceeded. The job cannot continue until "
            "the quota resets (midnight Pacific Time). Try again tomorrow or "
            "request a quota increase from Google."
        )
    elif "quota exceeded" in error.lower() and "youtube" in error.lower():
        error = (
            "YouTube API daily quota exceeded. The job cannot continue until "
            "the quota resets (midnight Pacific Time). Try again tomorrow or "
            "request a quota increase from Google."
        )

    # The common failure path is an exception mid-transaction — e.g. a UNIQUE
    # violation during commit leaves the session in PendingRollbackError. In
    # that state every query raises until the session is rolled back, which
    # would make the failure handler itself silently fail and leave the job
    # stuck in a transient status. Roll back first so the subsequent writes
    # can land. Fall back to a fresh session if the existing one is too far
    # gone to recover.
    try:
        db.rollback()
    except Exception:
        logger.exception(f"[job:{job_id}] _handle_failure: rollback itself failed")

    try:
        job = _get_job(db, job_id)
        if job:
            _update_job(db, job, status="failed", error_message=error)
        progress_service.publish_error(job_id, error)
    except Exception:
        logger.exception(f"[job:{job_id}] _handle_failure also failed while recording error: {error!r}")
        # Last-ditch: open a fresh session and update the row directly so the
        # UI doesn't hang on a transient status.
        try:
            fresh = SessionLocal()
            try:
                job = fresh.query(Job).filter(Job.id == job_id).first()
                if job is not None:
                    job.status = "failed"
                    job.error_message = error
                    job.updated_at = datetime.now(timezone.utc)
                    fresh.commit()
            finally:
                fresh.close()
        except Exception:
            logger.exception(f"[job:{job_id}] _handle_failure: fresh-session fallback also failed")
