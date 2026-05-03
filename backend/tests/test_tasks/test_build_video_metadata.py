"""Lock the `_build_video_metadata()` helper to its polymorphic contract.

This is the choke-point function that lifts per-document fields from
the `Document` row into the metadata dict the chunker writes to Chroma.
Before the M-1.6 follow-up enrichment, it returned only YouTube-shaped
fields, which meant social-media chunks (Reddit / HN / Mastodon /
Bluesky) lost their source identity at the chunking layer and rendered
as YouTube citations in production.

These tests pin the keys the helper must emit so future refactors
don't regress the citation pipeline silently.
"""
from types import SimpleNamespace

from app.tasks.job_tasks import _build_video_metadata


def _doc(**overrides) -> SimpleNamespace:
    """Build a Document-like object with the attributes the helper reads.

    Tests don't need a real SQLAlchemy ORM instance because the helper
    only reads attributes, never performs queries. SimpleNamespace gives
    us the duck-typed shape with one line of setup.
    """
    base = {
        "video_id": "abc123",
        "title": "Sample title",
        "channel_name": "Test Channel",
        "channel_id": "UCxxx",
        "url": "https://youtube.com/watch?v=abc123",
        "published_at": None,
        "duration_seconds": 120,
        "transcript_language": "en",
        "source_type": "video",
        "source_id": "abc123",
        "source_url": "https://youtube.com/watch?v=abc123",
        "source_metadata_json": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_video_doc_emits_legacy_youtube_fields():
    """Default video documents still serialize the YouTube-shaped block."""
    doc = _doc()
    md = _build_video_metadata(doc, language=None)
    assert md["video_id"] == "abc123"
    assert md["title"] == "Sample title"
    assert md["channel_name"] == "Test Channel"
    assert md["channel_id"] == "UCxxx"
    assert md["url"] == "https://youtube.com/watch?v=abc123"
    assert md["language"] == "en"


def test_video_doc_emits_polymorphic_fields_with_video_defaults():
    """Source_type='video' rows still carry the polymorphic block; the
    fields are largely redundant with the legacy fields here, but they
    must be populated so the qa_agent's polymorphic dispatch finds them
    and so future refactors can drop the legacy fields safely."""
    doc = _doc()
    md = _build_video_metadata(doc, language=None)
    assert md["source_type"] == "video"
    assert md["source_id"] == "abc123"
    assert md["source_url"] == "https://youtube.com/watch?v=abc123"
    assert md["permalink"] == "https://youtube.com/watch?v=abc123"
    # Per-source-specific fields are blank for video.
    assert md["author"] == ""
    assert md["subreddit"] == ""
    assert md["instance"] == ""


def test_reddit_doc_lifts_subreddit_and_author_from_source_metadata():
    """Reddit-specific fields live in `source_metadata_json` per the
    L1 schema; the helper lifts them up to top-level keys the chunker
    can pass through to Chroma."""
    doc = _doc(
        video_id="reddit:abc",
        source_type="reddit_post",
        source_id="reddit:abc",
        source_url="https://www.reddit.com/r/economics/comments/abc",
        source_metadata_json={
            "subreddit": "economics",
            "author": "supply_chain_pro",
            "score": 42,
            "comment_count": 15,
        },
    )
    md = _build_video_metadata(doc, language=None)
    assert md["source_type"] == "reddit_post"
    assert md["source_id"] == "reddit:abc"
    assert md["permalink"] == "https://www.reddit.com/r/economics/comments/abc"
    assert md["subreddit"] == "economics"
    assert md["author"] == "supply_chain_pro"


def test_hn_doc_lifts_author_no_subreddit():
    doc = _doc(
        video_id="hn:42000",
        source_type="hn_story",
        source_id="hn:42000",
        source_url="https://news.ycombinator.com/item?id=42000",
        source_metadata_json={"author": "throwaway_dev", "points": 142},
    )
    md = _build_video_metadata(doc, language=None)
    assert md["source_type"] == "hn_story"
    assert md["author"] == "throwaway_dev"
    assert md["subreddit"] == ""  # HN has no subreddit
    assert md["permalink"] == "https://news.ycombinator.com/item?id=42000"


def test_mastodon_doc_lifts_instance_and_author():
    doc = _doc(
        video_id="mastodon:111222",
        source_type="mastodon_post",
        source_id="mastodon:111222",
        source_url="https://mastodon.social/@privacynerd/111222",
        source_metadata_json={
            "author": "privacynerd",
            "instance": "mastodon.social",
            "favourites_count": 50,
        },
    )
    md = _build_video_metadata(doc, language=None)
    assert md["source_type"] == "mastodon_post"
    assert md["author"] == "privacynerd"
    assert md["instance"] == "mastodon.social"


def test_bluesky_doc_lifts_author_no_instance_field():
    """Bluesky handles already include the instance/domain
    (`alice.bsky.social`); we don't carry a separate instance field
    for Bluesky in source_metadata, so it stays empty."""
    doc = _doc(
        video_id="bluesky:at://did:plc:abc/app.bsky.feed.post/100",
        source_type="bluesky_post",
        source_id="bluesky:at://did:plc:abc/app.bsky.feed.post/100",
        source_url="https://bsky.app/profile/alice.bsky.social/post/100",
        source_metadata_json={
            "author": "alice.bsky.social",
            "likeCount": 25,
        },
    )
    md = _build_video_metadata(doc, language=None)
    assert md["source_type"] == "bluesky_post"
    assert md["author"] == "alice.bsky.social"
    assert md["instance"] == ""
    assert md["permalink"] == "https://bsky.app/profile/alice.bsky.social/post/100"


def test_missing_source_metadata_json_doesnt_crash():
    """Older Document rows may not have the column populated. Helper
    must default gracefully rather than raising AttributeError /
    TypeError on `None.get(...)`."""
    doc = _doc(source_metadata_json=None)
    md = _build_video_metadata(doc, language=None)
    assert md["author"] == ""
    assert md["subreddit"] == ""
    assert md["instance"] == ""


def test_non_dict_source_metadata_json_doesnt_crash():
    """Defensive: corrupt rows where source_metadata_json deserialized
    to a non-dict (a string, list) shouldn't take down the chunker."""
    doc = _doc(source_metadata_json=["malformed"])
    md = _build_video_metadata(doc, language=None)
    assert md["author"] == ""
    assert md["subreddit"] == ""


def test_explicit_language_overrides_doc_language():
    """Whisper-fallback path passes the actual detected language; that
    must win over the Document's stored transcript_language."""
    doc = _doc(transcript_language="en")
    md = _build_video_metadata(doc, language="es")
    assert md["language"] == "es"


def test_language_falls_back_to_doc_then_en():
    doc = _doc(transcript_language=None)
    md = _build_video_metadata(doc, language=None)
    assert md["language"] == "en"


def test_permalink_falls_back_to_url_when_source_url_missing():
    """Older rows pre-S-1.5.5 may have video.url but no source_url;
    we still want a usable permalink for the citation."""
    doc = _doc(source_url=None)
    md = _build_video_metadata(doc, language=None)
    assert md["permalink"] == "https://youtube.com/watch?v=abc123"
