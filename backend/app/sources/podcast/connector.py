"""Podcast connector — exposes the BaseConnector contract for
``source_type='podcast_episode'``.

Discovery surface: iTunes Search for shows + per-show RSS feed for
episodes. Text extraction: in-feed `<podcast:transcript>` when
present, falling back to OpenAI Whisper on the audio enclosure.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from itertools import chain, zip_longest
from typing import Any, Iterator

import httpx

from app.config import settings
from app.services.source_failure import SearchFailed, TranscriptionEmpty
from app.sources import registry
from app.sources._topic_terms import term_keys, topic_keys, topic_queries
from app.sources.base import BaseConnector
from app.sources.podcast import client as podcast_client
from app.sources.podcast import flatten as podcast_flatten
from app.sources.types import (
    Candidate,
    CreatorMetadata,
    ExtractedText,
    SourceMetadata,
)
from app.utils.log_redaction import provider_error_text
from app.utils.shared_url_log import host_of, loggable_id, shared_url_fetch

logger = logging.getLogger(__name__)

SOURCE_TYPE = "podcast_episode"
SOURCE_ID_PREFIX = "podcast:"

# How much of the topic an episode's title and description must name for it
# to count as on topic: most of it, so "nuclear power" is not met by an
# episode on boardroom power, and not all of it, so a long topic can match.
_MATCH_SHARE = 0.6


def _strip_prefix(source_id: str) -> str:
    """``podcast:abc-guid`` → ``abc-guid``."""
    if source_id.startswith(SOURCE_ID_PREFIX):
        return source_id[len(SOURCE_ID_PREFIX) :]
    return source_id


def _entry_field(entry: Any, key: str, default: Any = None) -> Any:
    """Read `key` from a feedparser entry, tolerating both
    `FeedParserDict` (attr access) and plain `dict` (key access).

    feedparser exposes entries as `FeedParserDict` which supports both
    `entry.key` and `entry["key"]`. But callers that synthesise feed
    entries in tests typically use plain dicts (no attribute access).
    Helper unifies the two so the connector works against either shape.
    """
    val = getattr(entry, key, None)
    if val is None and hasattr(entry, "get"):
        try:
            val = entry.get(key)
        except (TypeError, AttributeError):
            val = None
    return val if val is not None else default


def _episode_guid(entry: Any) -> str:
    """Extract a stable GUID from a feedparser entry.

    RSS-2.0 requires `<guid>` on every item but in practice the
    field is sometimes missing or duplicated. Fallback chain:
    ``id`` (feedparser's normalised guid) → ``link`` (episode URL
    on the show site) → enclosure URL → SHA-1 of (title + pubdate)
    as a last-resort synthetic id.
    """
    for key in ("id", "guid"):
        val = getattr(entry, key, None) or (
            entry.get(key) if hasattr(entry, "get") else None
        )
        if val:
            return str(val)
    link = getattr(entry, "link", None)
    if link:
        return str(link)
    enc = _enclosure_url(entry)
    if enc:
        return enc
    title = getattr(entry, "title", "") or ""
    published = (
        getattr(entry, "published", "")
        or getattr(entry, "updated", "")
        or ""
    )
    return hashlib.sha1(f"{title}|{published}".encode()).hexdigest()


def _enclosure_url(entry: Any) -> str:
    """Pull the audio enclosure URL out of a feedparser entry."""
    enclosures = _entry_field(entry, "enclosures") or []
    for enc in enclosures:
        url = enc.get("href") if hasattr(enc, "get") else getattr(enc, "href", None)
        # iTunes feeds tag audio/* enclosures; we tolerate missing type too
        if url:
            return str(url)
    return ""


def _entry_published_at(entry: Any) -> datetime | None:
    """Convert feedparser's `published_parsed` (a 9-tuple) to a UTC datetime."""
    parsed = getattr(entry, "published_parsed", None) or getattr(
        entry, "updated_parsed", None
    )
    if not parsed:
        return None
    try:
        # feedparser tuples are time.struct_time; first 6 fields are
        # (year, month, day, hour, minute, second).
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _entry_summary(entry: Any) -> str:
    return _entry_field(entry, "summary") or _entry_field(entry, "subtitle") or ""


def _select_entries(entries: list[Any], topic: str, count: int) -> list[Any]:
    """The ``count`` entries a show contributes to ``topic`` (T-1.7.1.3).

    Episodes that name most of the topic come first, those naming it in the
    title ahead of those that only mention it, and the feed's own order breaks
    ties. The rest of the count comes from the head of the feed, the newest,
    so a show with no match contributes exactly what it always did. Reads only
    what the feed already holds: no LLM and no audio.
    """
    head = entries[:count]
    wanted = topic_keys(topic)
    if not wanted:
        return head
    needed = math.ceil(len(wanted) * _MATCH_SHARE)
    matches: list[tuple[int, int, int]] = []
    for index, entry in enumerate(entries):
        in_title = wanted & term_keys(_entry_field(entry, "title", "") or "")
        named = in_title | (wanted & term_keys(_entry_summary(entry)))
        if len(named) >= needed:
            matches.append((-len(in_title), -len(named), index))
    chosen = [entries[index] for _, _, index in sorted(matches)[:count]]
    taken = {id(entry) for entry in chosen}
    fill = [entry for entry in head if id(entry) not in taken]
    return chosen + fill[: count - len(chosen)]


def _entry_to_candidate(entry: Any, feed_url: str, show_name: str | None) -> Candidate:
    """Convert a feedparser entry into a `Candidate`."""
    guid = _episode_guid(entry)
    title = _entry_field(entry, "title", "") or ""
    enclosure = _enclosure_url(entry)
    summary = _entry_summary(entry)
    return Candidate(
        source_type=SOURCE_TYPE,
        source_id=f"{SOURCE_ID_PREFIX}{guid}",
        title=title or "(untitled episode)",
        # Show page URL or enclosure URL — the entry's `link` is the
        # episode page on the show site if present, otherwise we fall
        # back to the audio file.
        source_url=_entry_field(entry, "link", "") or enclosure,
        creator_external_id=feed_url,  # feed URL = canonical creator id
        creator_name=show_name or None,
        duration_seconds=_parse_itunes_duration(
            _entry_field(entry, "itunes_duration", "")
        ),
        published_at=_entry_published_at(entry),
        thumbnail_url=_entry_thumbnail(entry),
        description=(summary[:500] or None) if summary else None,
        extra={
            "enclosure_url": enclosure,
            "feed_url": feed_url,
            **{
                k: v
                for k in ("itunes_explicit", "itunes_episode")
                if (v := _entry_field(entry, k))
            },
        },
    )


def _entry_thumbnail(entry: Any) -> str | None:
    """Fish a thumbnail out of various tag locations."""
    image = getattr(entry, "image", None)
    if isinstance(image, dict):
        href = image.get("href")
        if href:
            return str(href)
    itunes_image = getattr(entry, "itunes_image", None)
    if isinstance(itunes_image, dict):
        href = itunes_image.get("href")
        if href:
            return str(href)
    media_thumbnail = getattr(entry, "media_thumbnail", None)
    if isinstance(media_thumbnail, list) and media_thumbnail:
        first = media_thumbnail[0]
        if isinstance(first, dict):
            url = first.get("url")
            if url:
                return str(url)
    return None


_DURATION_HMS_RE = re.compile(r"^\s*(?:(\d+):)?(\d+):(\d+)\s*$")


def _parse_itunes_duration(raw: str) -> int | None:
    """Parse `itunes:duration` to seconds.

    Common formats: `HH:MM:SS`, `MM:SS`, or bare integer seconds.
    Returns None on anything else.
    """
    if not raw:
        return None
    raw = str(raw).strip()
    if raw.isdigit():
        try:
            return int(raw)
        except ValueError:
            return None
    m = _DURATION_HMS_RE.match(raw)
    if not m:
        return None
    h, mm, ss = m.groups()
    try:
        total = (int(h) if h else 0) * 3600 + int(mm) * 60 + int(ss)
        return total
    except (TypeError, ValueError):
        return None


@shared_url_fetch()
def _resolve_transcript_segments(
    entry: Any, episode_url: str
) -> list[dict[str, Any]] | None:
    """If the entry carries a `<podcast:transcript>` tag, fetch + parse it.

    Returns canonical-shape segments on success, ``None`` when the tag
    isn't present or the fetched content can't be parsed. Caller falls
    through to Whisper when this returns None.

    `<podcast:transcript>` is a Podcast Index 2.0 tag; feedparser
    surfaces it as ``entry.podcast_transcript`` (single dict) or
    ``entry.podcast_transcripts`` (list of dicts), depending on
    feedparser version. We tolerate both.
    """
    transcripts: list[dict] = []
    pt_single = _entry_field(entry, "podcast_transcript")
    if isinstance(pt_single, dict):
        transcripts.append(pt_single)
    pt_list = _entry_field(entry, "podcast_transcripts")
    if isinstance(pt_list, list):
        transcripts.extend(d for d in pt_list if isinstance(d, dict))

    if not transcripts:
        return None

    # Prefer SRT / VTT over HTML / JSON formats (those are harder to
    # convert to timestamped segments and not worth the complexity yet).
    def _format_priority(t: dict) -> int:
        ttype = (t.get("type") or "").lower()
        if "srt" in ttype:
            return 0
        if "vtt" in ttype:
            return 1
        return 99

    transcripts.sort(key=_format_priority)
    chosen = transcripts[0]
    if _format_priority(chosen) == 99:
        # Only HTML/JSON available — defer to Whisper.
        return None

    url = chosen.get("url") or chosen.get("href")
    if not url:
        return None

    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": settings.PODCAST_USER_AGENT},
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=True,
        )
        resp.raise_for_status()
        body = resp.text
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        logger.warning(
            "podcast: in-feed transcript fetch failed for %s: %s",
            host_of(url),
            type(e).__name__,
        )
        return None

    ttype = (chosen.get("type") or "").lower()
    if "vtt" in ttype:
        return podcast_flatten.parse_vtt(body)
    return podcast_flatten.parse_srt(body)


def _whisper_transcribe_audio(
    audio_url: str, source_id: str, job_id: str
) -> list[dict[str, Any]] | None:
    """Download `audio_url` and transcribe via OpenAI Whisper.

    Reuses the existing `_whisper_transcribe_with_retry` helper from
    ``app.services.youtube_service`` so retries / error-classification
    stay consistent with the YouTube fallback path. Returns canonical
    `{text, start, duration}` segments or None on failure.

    An episode past Whisper's 25 MB upload cap, which is most long shows,
    goes through the same chunked path as a long YouTube video
    (`_transcribe_in_chunks`), so it needs ffmpeg on PATH. Without ffmpeg it
    is unavailable like any other failure here.

    Fail-soft: any error (HTTP fetch / Whisper call / file IO) is
    logged + caught here, and the function returns None. Caller
    treats None as "text unavailable". The exceptions are Whisper answers
    that were billed and left no text: a split episode that fails part-way
    (`TranscriptionCutShort`, T-1.7.1.5) and an episode that came back with
    no words (`TranscriptionEmpty`, T-1.7.1.7). Both go up to the job, so
    its Whisper limits count what was billed.
    """
    if not audio_url:
        return None
    from app.services import llm_service

    label = loggable_id(source_id)

    # T-5.6.13: the tenant's key when they brought one, as Echo recordings, so
    # an install with no key of its own can still read their episodes.
    api_key = llm_service.whisper_api_key()
    if not api_key:
        logger.warning(
            "podcast: no OpenAI key, yours or the install's; cannot "
            "Whisper-transcribe %s",
            label,
        )
        return None

    # Suffix from the URL's path — Whisper uses the file extension to
    # detect format. Default to .mp3 since that's the dominant podcast
    # format and Whisper accepts it readily.
    suffix = ".mp3"
    if "." in audio_url.rsplit("/", 1)[-1]:
        ext = audio_url.rsplit(".", 1)[-1].split("?", 1)[0].lower()
        if ext in ("mp3", "m4a", "wav", "ogg", "flac", "webm", "mp4"):
            suffix = f".{ext}"

    # Stream to a temp file: the Whisper API takes a file handle, and a worker
    # should not hold a 150 MB episode in memory (T-1.7.1.2). The directory
    # goes on every way out, a failed download's partial file and any
    # chunks included.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work_dir:
        tmp_path = os.path.join(work_dir, f"episode{suffix}")
        try:
            audio_size = podcast_client.get_client().fetch_audio_to_file(
                audio_url, tmp_path
            )
        except (httpx.HTTPError, httpx.InvalidURL, OSError, podcast_client.AudioTooLargeError) as e:
            logger.warning(
                "podcast: audio fetch failed for %s (%s): %s",
                label,
                host_of(audio_url),
                type(e).__name__,
            )
            return None
        if audio_size == 0:
            logger.warning("podcast: empty audio for %s (%s)", label, host_of(audio_url))
            return None

        # Reuse the YouTube Whisper helper. Tag is a free-form log
        # prefix, and the helper's id is only ever logged, so it gets the
        # label, which is correlatable and holds no URL.
        from openai import OpenAI

        from app.services import youtube_service
        from app.services.youtube_service import _whisper_transcribe_with_retry

        client = OpenAI(api_key=api_key)
        tag = f"[job:{job_id}] [podcast]" if job_id else "[podcast]"
        if audio_size > youtube_service.WHISPER_MAX_FILE_BYTES:
            result = youtube_service._transcribe_in_chunks(
                client, tmp_path, work_dir, label, tag
            )
            return result[0] if result else None

        size_mb = audio_size / (1024 * 1024)
        try:
            response = _whisper_transcribe_with_retry(
                client,
                tmp_path,
                label,
                tag,
                size_mb,
            )
        except Exception as e:
            logger.warning(
                "podcast: Whisper transcription failed for %s: %s",
                label,
                provider_error_text(e),
            )
            return None

        if response is None:
            return None
        # Whisper "verbose_json" returns `.segments` (Pydantic model
        # in newer SDKs; dict-list in older). Coerce both.
        segs_raw = getattr(response, "segments", None)
        if segs_raw is None and isinstance(response, dict):
            segs_raw = response.get("segments")
        # Each segment may be a Pydantic object; convert to dict.
        normalised: list[dict] = []
        for s in segs_raw or []:
            if hasattr(s, "model_dump"):
                normalised.append(s.model_dump())
            elif isinstance(s, dict):
                normalised.append(s)
        segments = podcast_flatten.whisper_segments_to_canonical(normalised)
        heard = youtube_service._whisper_duration(response)
        if not segments:
            # T-1.7.1.8: words with no `segments`, which YouTube's path has
            # always kept as pseudo-segments spread over what Whisper heard.
            # The same helper, so the episode is an ordinary transcription,
            # charged once by the job like any other.
            segments = _end_where_whisper_stopped(
                youtube_service._synthesize_pseudo_segments(_whisper_text(response), heard), heard
            )
            if segments:
                logger.info(
                    "%s Whisper returned text with no segments for %s: %d pseudo-segments",
                    tag,
                    label,
                    len(segments),
                )
        if not segments:
            # Answered and billed, with no words (T-1.7.1.7): up to the job,
            # whose Whisper limits count it as they count a cut-short one.
            raise TranscriptionEmpty(heard)
        return segments


def _whisper_text(response: Any) -> str:
    """The whole-text field of a verbose_json answer, by attribute (the SDK's
    model) or by key (an older SDK's dict); "" when there is none."""
    text = response.get("text") if isinstance(response, dict) else getattr(response, "text", None)
    return text.strip() if isinstance(text, str) else ""


def _end_where_whisper_stopped(segments: list[dict], heard: float) -> list[dict]:
    """Stretch the last pseudo-segment so the timeline ends at ``heard``.

    ``_synthesize_pseudo_segments`` gives a segment only to a 30 s slot that
    gets a word, so sparse speech (ten words in an hour of music) ends its
    segments after about 30 s per word (300 s). The minute cap charges an
    episode by where its transcript ends when the feed declares no length
    (``WhisperMinutes.charge``), and Whisper billed every second it heard, so
    the timeline must reach that far. Every start stays as the helper set it;
    only the last segment's duration grows, over audio that held no words.
    """
    if segments and heard > 0:
        last = segments[-1]
        start = float(last.get("start") or 0.0)
        if start + float(last.get("duration") or 0.0) < heard:
            last["duration"] = round(heard - start, 3)
    return segments


class PodcastConnector(BaseConnector):
    """`BaseConnector` for ``source_type='podcast_episode'``."""

    source_type = SOURCE_TYPE

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        instructions: str = "",
        limit: int = 10,
    ) -> list[Candidate]:
        """Two-tier search: iTunes for shows, RSS for episodes.

        For each top-N show iTunes returns, fetch the show's RSS feed
        and take K episodes: those on the topic first, then its most
        recent (``_select_entries``). Up to
        ``PODCAST_SEARCH_TOP_N_SHOWS * PODCAST_EPISODES_PER_SHOW``
        candidates total, capped at `limit`.

        The cap is applied by taking one episode from each show in turn:
        a run's share of the budget is small (D-114), and filling it show
        by show would hand nearly all of it to the first show iTunes ranks.

        A failure stays raised, so the dispatcher can tell it from "nothing
        found" (T-1.5.14.1): iTunes itself, or every feed it pointed at. One
        feed failing out of three only costs that show. Feeds fail as
        ``SearchFailed``: each is some show's own host, and a 403 from one
        says nothing about the search, which iTunes has already answered.
        """
        client = podcast_client.get_client()
        results: list = []
        for attempt in topic_queries(query):
            payload = client.itunes_search(
                attempt, limit=settings.PODCAST_SEARCH_TOP_N_SHOWS
            )
            results = (
                payload.get("results") if isinstance(payload, dict) else None
            ) or []
            if results:
                break

        per_show: list[list[Candidate]] = []
        feed_failure: Exception | None = None
        for show in results[: settings.PODCAST_SEARCH_TOP_N_SHOWS]:
            if not isinstance(show, dict):
                continue
            feed_url = show.get("feedUrl")
            if not feed_url:
                continue
            show_name = show.get("collectionName") or show.get("trackName") or ""
            try:
                feed = client.fetch_feed(feed_url)
            except Exception as e:
                logger.warning(
                    "podcast: feed fetch failed for %s: %s", host_of(feed_url), type(e).__name__
                )
                feed_failure = e
                continue
            entries = (feed.get("entries") if isinstance(feed, dict) else None) or []
            per_show.append(
                [
                    _entry_to_candidate(entry, feed_url, show_name)
                    for entry in _select_entries(
                        list(entries), query, settings.PODCAST_EPISODES_PER_SHOW
                    )
                ]
            )
        if feed_failure is not None and not per_show:
            raise SearchFailed("no feed iTunes named could be read") from feed_failure
        in_turn = chain.from_iterable(zip_longest(*per_show))
        return [c for c in in_turn if c is not None][: max(0, limit)]

    def list_creator_items(
        self,
        creator_external_id: str,
        since: datetime | None = None,
        *,
        limit: int | None = None,
        job_id: str = "",
    ) -> Iterator[Candidate]:
        """Iterate episodes from a podcast feed.

        `creator_external_id` is the RSS feed URL — opaque to the
        connector apart from being the canonical id.
        """
        if not creator_external_id:
            return
        client = podcast_client.get_client()
        try:
            feed = client.fetch_feed(creator_external_id)
        except Exception as e:
            logger.warning(
                "podcast: feed fetch failed for %s: %s",
                host_of(creator_external_id),
                type(e).__name__,
                extra={"job_id": job_id},
            )
            return
        show_name = ""
        feed_meta = feed.get("feed") if isinstance(feed, dict) else None
        if isinstance(feed_meta, dict):
            show_name = (
                feed_meta.get("title") or feed_meta.get("subtitle") or ""
            )
        entries = (feed.get("entries") if isinstance(feed, dict) else None) or []
        page_limit = limit if limit is not None else 25
        for entry in entries[:page_limit]:
            yield _entry_to_candidate(entry, creator_external_id, show_name)

    def resolve_creator_id(
        self, hint: str, *, job_id: str = ""
    ) -> str | None:
        """Translate user-supplied podcast hints to canonical RSS feed URLs.

        Accepts:
        - direct RSS feed URL (returned as-is)
        - ``https://podcasts.apple.com/.../id1234567890`` URL → resolves
          to the show's RSS via iTunes lookup
        """
        if not hint:
            return None
        cleaned = hint.strip()
        # Direct RSS heuristic — if the URL looks RSS-shaped, accept it.
        # We don't fetch-to-validate here because that would slow the
        # submit-research form; the next step (list_creator_items) will
        # surface a clear error if the URL is bogus.
        if cleaned.startswith(("http://", "https://")) and "/podcasts.apple.com/" not in cleaned:
            return cleaned

        itunes_id = podcast_client._itunes_id_from_url(cleaned)
        if itunes_id:
            client = podcast_client.get_client()
            try:
                payload = client.itunes_lookup(itunes_id)
            except Exception as e:
                logger.warning(
                    "podcast: iTunes lookup failed for id %s: %s",
                    itunes_id,
                    e,
                    extra={"job_id": job_id},
                )
                return None
            results = (
                payload.get("results") if isinstance(payload, dict) else None
            ) or []
            if not results:
                return None
            first = results[0]
            if isinstance(first, dict):
                return first.get("feedUrl") or None

        return None

    def fetch_creator(self, creator_external_id: str) -> CreatorMetadata | None:
        """Fetch show-level metadata from the RSS feed."""
        if not creator_external_id:
            return None
        client = podcast_client.get_client()
        try:
            feed = client.fetch_feed(creator_external_id)
        except Exception as e:
            logger.warning(
                "podcast: fetch_creator feed-fetch failed for %s: %s",
                host_of(creator_external_id),
                type(e).__name__,
            )
            return None
        feed_meta = feed.get("feed") if isinstance(feed, dict) else None
        if not isinstance(feed_meta, dict):
            return None
        return CreatorMetadata(
            creator_external_id=creator_external_id,
            name=feed_meta.get("title") or "",
            url=feed_meta.get("link") or creator_external_id,
            description=(feed_meta.get("subtitle") or feed_meta.get("summary") or "")[:500] or None,
            subscriber_count=None,  # iTunes doesn't expose subscriber counts
            extra={
                k: feed_meta.get(k)
                for k in ("language", "itunes_author", "itunes_explicit")
                if feed_meta.get(k)
            },
        )

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------
    def fetch_metadata(
        self,
        source_ids: list[str],
        *,
        job_id: str = "",
    ) -> dict[str, SourceMetadata]:
        """Per-id metadata is mostly already in the Candidate; this is
        a no-op that returns empty for now.

        Rationale: we already have full episode metadata from
        `_entry_to_candidate` in `search()` / `list_creator_items()`.
        Re-fetching the feed just to re-parse the same entries is
        wasteful. Future enhancement: cache feed-parses keyed by
        feed URL with a 1-hour TTL so re-running the same job
        within a session reuses the parse.
        """
        return {}

    # ------------------------------------------------------------------
    # Text payload
    # ------------------------------------------------------------------
    def fetch_text(
        self,
        candidate: Candidate,
        *,
        job_id: str = "",
        query: str = "",
        allow_whisper: bool = True,
    ) -> ExtractedText | None:
        """Return episode segments via in-feed transcript or Whisper.

        Strategy:
        1. Re-fetch the show feed so we have the latest entry data
           (the Candidate may have been built hours ago).
        2. Find the entry matching the candidate's GUID.
        3. Try the in-feed `<podcast:transcript>` first; if SRT/VTT,
           parse directly.
        4. Else download the audio enclosure and Whisper-transcribe,
           unless ``allow_whisper`` is False (as for the YouTube
           connector): a topic run's search phase reads in-feed
           transcripts only, and extraction passes the job's remaining
           ``WHISPER_MAX_PER_JOB`` budget (S-1.5.13).
        5. Attach episode-level `extra` (author, comment_url with
           ``#t=`` time fragment) to every segment so per-segment
           reply-anchor citations get a deep-linkable timestamp.

        Per [D-007/D-014/D-021/D-023](../../../docs/decisions.md), no
        social_classify call here — podcasts don't carry the
        stance/sentiment/framing axes the social classifier was built
        for. Future enhancement: a podcast-tailored classifier could
        score topical relevance differently (the topic-relevance axis
        from D-021 still applies, but stance/sentiment less so).
        """
        guid = _strip_prefix(candidate.source_id)
        feed_url = candidate.creator_external_id or candidate.extra.get("feed_url")
        if not feed_url:
            logger.warning(
                "podcast fetch_text: no feed_url for %s; cannot fetch entry",
                loggable_id(candidate.source_id),
            )
            return None
        client = podcast_client.get_client()
        try:
            feed = client.fetch_feed(feed_url)
        except Exception as e:
            logger.warning(
                "podcast fetch_text: feed fetch failed for %s: %s",
                host_of(feed_url),
                type(e).__name__,
                extra={"job_id": job_id},
            )
            return None

        entry = _find_entry_by_guid(feed, guid)
        if entry is None:
            logger.warning(
                "podcast fetch_text: no entry with guid %s in feed %s",
                loggable_id(guid),
                host_of(feed_url),
            )
            return None

        # Episode-level identity for the per-segment `extra` block.
        episode_url = (
            _entry_field(entry, "link", "")
            or _enclosure_url(entry)
            or candidate.source_url
        )
        author = (
            _entry_field(entry, "author", "")
            or candidate.creator_name
            or ""
        )

        # 1. In-feed transcript (preferred).
        segments = _resolve_transcript_segments(entry, episode_url)
        text_source = "podcast_transcript"

        # 2. Whisper fallback.
        if not segments and not allow_whisper:
            logger.info(
                "podcast fetch_text: no in-feed transcript for %s and Whisper "
                "not allowed here; text unavailable for now",
                loggable_id(candidate.source_id),
                extra={"job_id": job_id},
            )
            return None
        if not segments:
            audio_url = _enclosure_url(entry)
            segments = _whisper_transcribe_audio(audio_url, candidate.source_id, job_id)
            text_source = "podcast_whisper"

        if not segments:
            return None

        segments = podcast_flatten.attach_episode_extra(
            segments, episode_url, author
        )
        word_count = sum(len(seg.get("text", "").split()) for seg in segments)

        # Language detection: feedparser exposes `<language>` on the
        # feed root; episode-level language is rare. Prefer episode if
        # set, fall back to feed-level.
        language = (
            _entry_field(entry, "language")
            or (
                feed.get("feed", {}).get("language")
                if isinstance(feed, dict) and isinstance(feed.get("feed"), dict)
                else None
            )
            or "en"
        )

        return ExtractedText(
            segments=segments,
            language=language,
            text_source=text_source,
            word_count=word_count,
            extra={"episode_url": episode_url, "feed_url": feed_url},
        )


def _find_entry_by_guid(feed: Any, guid: str) -> Any | None:
    """Locate the feedparser entry matching `guid`."""
    entries = (feed.get("entries") if isinstance(feed, dict) else None) or []
    for entry in entries:
        if _episode_guid(entry) == guid:
            return entry
    return None


# Eager registration — importing this module wires the connector for
# `source_type="podcast_episode"`.
_INSTANCE = PodcastConnector()
registry.register(_INSTANCE)
