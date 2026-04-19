import json
import logging
from datetime import datetime, timezone

from app.config import settings
from app.database import SessionLocal
from app.models.job import Job
from app.models.video import Video
from app.services import chroma_service, progress_service, youtube_service
from app.tasks.celery_app import celery_app
from app.utils.chunking import chunk_transcript
from app.utils.html_builder import build_report_html, save_report

logger = logging.getLogger(__name__)


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

        # Run Search Agent
        from app.agents.search_agent import run_search_agent
        logger.info(f"[job:{job_id}] Starting Search Agent for topic: '{job.topic}'")
        curated_videos = run_search_agent(
            topic=job.topic,
            num_videos=job.num_videos,
            search_instructions=job.search_instructions or "",
            min_duration=job.min_duration_minutes,
            max_duration=job.max_duration_minutes,
            channel_type_filters=json.loads(job.channel_type_filters) if job.channel_type_filters else [],
        )
        logger.info(f"[job:{job_id}] Search Agent complete: found {len(curated_videos)} candidate videos")

        progress_service.publish_progress(job_id, "searching", 15,
                                          f"Found {len(curated_videos)} videos. Fetching details...")

        # Save videos to DB
        for v in curated_videos:
            video = Video(
                job_id=job_id,
                video_id=v.get("video_id", ""),
                title=v.get("title", "Unknown"),
                channel_name=v.get("channel_name", "Unknown"),
                channel_id=v.get("channel_id", ""),
                url=v.get("url", f"https://www.youtube.com/watch?v={v.get('video_id', '')}"),
                duration_seconds=v.get("duration_seconds", 0),
                published_at=None,
                thumbnail_url=v.get("thumbnail_url"),
                approved=True,
            )
            db.add(video)
        db.commit()
        logger.info(f"[job:{job_id}] {len(curated_videos)} videos saved to DB, awaiting user approval")

        _update_job(db, job, status="awaiting_approval", progress_pct=20,
                    progress_message=f"Found {len(curated_videos)} videos. Please review and approve.")
        progress_service.publish_status_change(job_id, "searching", "awaiting_approval",
                                               f"Found {len(curated_videos)} videos. Please review and approve.")

    except Exception as e:
        logger.exception(f"[job:{job_id}] Topic job failed during search: {e}")
        _handle_failure(db, job_id, str(e))
    finally:
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
            channel_id = youtube_service.resolve_channel_id(channel_input, job_id=job_id)
            if not channel_id:
                logger.warning(f"[job:{job_id}] Could not resolve channel: '{channel_input}', skipping")
                continue

            logger.info(f"[job:{job_id}] Channel '{channel_input}' → {channel_id}, "
                        f"fetching up to {videos_per_channel} videos")

            # Fetch video IDs from channel
            video_ids = youtube_service.get_channel_videos(channel_id, max_results=videos_per_channel, job_id=job_id)
            logger.info(f"[job:{job_id}] Fetched {len(video_ids)} video IDs from channel {channel_id}")
            all_video_ids.extend(video_ids)

        logger.info(f"[job:{job_id}] All channels processed: {len(all_video_ids)} total video IDs before filtering")

        # Fetch details for all videos
        accepted_count = 0
        if all_video_ids:
            details = youtube_service.get_video_details(all_video_ids, job_id=job_id)

            # Apply duration filters
            for vid, info in details.items():
                dur_min = info.get("duration_seconds", 0) / 60
                if job.min_duration_minutes and dur_min < job.min_duration_minutes:
                    continue
                if job.max_duration_minutes and dur_min > job.max_duration_minutes:
                    continue

                video = Video(
                    job_id=job_id,
                    video_id=vid,
                    title=info.get("title", "Unknown"),
                    channel_name=info.get("channel_name", "Unknown"),
                    channel_id=info.get("channel_id", ""),
                    url=info.get("url", f"https://www.youtube.com/watch?v={vid}"),
                    duration_seconds=info.get("duration_seconds", 0),
                    thumbnail_url=info.get("thumbnail_url"),
                    approved=True,
                )
                db.add(video)
                accepted_count += 1
            db.commit()

        logger.info(f"[job:{job_id}] Duration filter applied: {accepted_count}/{len(all_video_ids)} videos accepted")

        video_count = len(job.videos)
        logger.info(f"[job:{job_id}] {video_count} videos saved to DB, awaiting user approval")
        _update_job(db, job, status="awaiting_approval", progress_pct=20,
                    progress_message=f"Found {video_count} videos. Please review and approve.")
        progress_service.publish_status_change(job_id, "searching", "awaiting_approval",
                                               f"Found {video_count} videos. Please review and approve.")

    except Exception as e:
        logger.exception(f"[job:{job_id}] Channel job failed during search: {e}")
        _handle_failure(db, job_id, str(e))
    finally:
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
        approved_videos = [v for v in job.videos if v.approved]
        total = len(approved_videos)
        logger.info(f"[job:{job_id}] Resuming job after approval: {total} approved videos "
                    f"to process (job_type={job.job_type})")

        _update_job(db, job, status="extracting", progress_pct=30,
                    progress_message=f"Extracting transcripts (0/{total})...",
                    celery_task_id=self.request.id)
        progress_service.publish_status_change(job_id, "awaiting_approval", "extracting",
                                               f"Extracting transcripts for {total} videos...")

        all_chunks = []
        fetched_count = 0

        for i, video in enumerate(approved_videos):
            if _is_cancelled(db, job_id):
                logger.info(f"[job:{job_id}] Job cancelled during extraction at video {i + 1}/{total}, exiting")
                return

            logger.info(f"[job:{job_id}] [{i + 1}/{total}] Fetching transcript: "
                        f"video_id={video.video_id} '{video.title[:60]}'")

            transcript = youtube_service.fetch_transcript(
                video.video_id,
                language=settings.DEFAULT_TRANSCRIPT_LANGUAGE,
                job_id=job_id,
            )

            if transcript:
                video.transcript_status = "fetched"
                word_count = sum(len(seg.get("text", "").split()) for seg in transcript)
                video.transcript_word_count = word_count
                video.transcript_language = settings.DEFAULT_TRANSCRIPT_LANGUAGE

                # Chunk the transcript
                chunks = chunk_transcript(
                    transcript,
                    chunk_size=settings.CHUNK_SIZE,
                    chunk_overlap=settings.CHUNK_OVERLAP,
                    video_metadata={
                        "video_id": video.video_id,
                        "title": video.title,
                        "channel_name": video.channel_name,
                        "channel_id": video.channel_id,
                        "url": video.url,
                        "published_at": video.published_at,
                        "duration_seconds": video.duration_seconds,
                        "language": settings.DEFAULT_TRANSCRIPT_LANGUAGE,
                    },
                )
                all_chunks.extend(chunks)
                fetched_count += 1
                logger.info(f"[job:{job_id}] [{i + 1}/{total}] Transcript OK: "
                            f"{word_count} words → {len(chunks)} chunks (video_id={video.video_id})")
            else:
                video.transcript_status = "unavailable"
                logger.warning(f"[job:{job_id}] [{i + 1}/{total}] Transcript unavailable: "
                               f"video_id={video.video_id} '{video.title[:60]}'")

            db.commit()

            progress_pct = 30 + int(25 * ((i + 1) / total))
            progress_service.publish_progress(
                job_id, "extracting", progress_pct,
                f"Extracted {fetched_count}/{total} transcripts...",
                data={"transcripts_fetched": fetched_count, "transcripts_total": total},
            )

        unavailable_count = total - fetched_count
        logger.info(f"[job:{job_id}] Extraction complete: {fetched_count} fetched, "
                    f"{unavailable_count} unavailable, {len(all_chunks)} total chunks")

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

        collection_name = f"job_{job_id.replace('-', '_')}"
        logger.info(f"[job:{job_id}] Building RAG: inserting {len(all_chunks)} chunks "
                    f"into ChromaDB collection '{collection_name}'")
        chroma_service.insert_chunks(job_id, all_chunks)
        _update_job(db, job, chroma_collection_name=collection_name)
        logger.info(f"[job:{job_id}] RAG built: {len(all_chunks)} chunks indexed in '{collection_name}'")

        progress_service.publish_progress(job_id, "building_rag", 70,
                                          f"Indexed {len(all_chunks)} chunks into knowledge base.")

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
        db.close()


def _handle_failure(db, job_id: str, error: str) -> None:
    """Set job to failed and publish error."""
    try:
        job = _get_job(db, job_id)
        if job:
            _update_job(db, job, status="failed", error_message=error)
        progress_service.publish_error(job_id, error)
    except Exception:
        pass
