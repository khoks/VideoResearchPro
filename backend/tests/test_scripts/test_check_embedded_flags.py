"""scripts/check_embedded_flags.py (T-5.2.24), run through its ``main``.

Before PR #440 a run stopped between extraction and the RAG build left its
documents flagged ``embedded_in_chroma`` with no chunk in Chroma, and every
later job reused them without inserting, so no Q&A retrieved them. The script
finds them by reading the database and the collection's metadata, and sorts
them by where their text lives; ``--write`` unflags them, and the next job
that selects one embeds it.

The library below holds every case on one in-memory Chroma: documents with
chunks named by ``document_id`` metadata, chunks named only by their id (the
scheme before 2026-10-19, ``{video_id}:{n}`` and ``{document_id}:{n}``),
stranded documents with cached text, with none, with a corrupt cache row and
with cached text that has no words, unflagged documents with and without
chunks, and chunks of a document that no longer exists.

Mutation checks: a check that ignores chunk ids counts the legacy documents
chunkless, and its write unflags them; without the write, the next job reuses
a stranded document and inserts nothing.
"""
from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.models.channel import Channel
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.transcript_cache import TranscriptCache
from app.services import chroma_service, embedded_flag_service, temporal_service
from app.sources.types import CreatorMetadata, ExtractedText
from app.tasks import job_tasks
from app.utils.chunking import chunk_transcript

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import check_embedded_flags as cef  # noqa: E402

# The real tasks, kept before any test patches the module's names.
RESUME = job_tasks.resume_job_after_approval
SYNC = job_tasks.execute_subscription_job
CHANNEL = "UCflagCheck00001"
WORDS = "The tidal barrage stores water at high tide and releases it through turbines"
SEGMENTS = [{"text": f"{WORDS}, part {i}.", "start": float(i * 5), "duration": 5.0} for i in range(6)]


@pytest.fixture
def ephemeral_chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    yield chroma_service
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def _document(db, source_type: str, source_id: str, *, flagged: bool, cache: str | None = None,
              video: bool = False, title: str = "A title the report must not print") -> Document:
    doc = Document(
        source_type=source_type, source_id=source_id, video_id=source_id if video else None,
        title=title, url=f"https://example.org/{source_id}", transcript_status="fetched",
        embedded_in_chroma=flagged,
    )
    db.add(doc)
    db.flush()
    if cache is not None:
        db.add(TranscriptCache(document_id=doc.document_id, video_id=doc.video_id,
                               segments_json=cache, language="en", source=source_type))
    return doc


def _chunks_for(doc: Document) -> list[dict]:
    """Chunks as a job writes them today: ``document_id`` metadata on each."""
    meta = {"document_id": doc.document_id, "source_type": doc.source_type,
            "source_id": doc.source_id, "title": doc.title}
    if doc.video_id:
        meta["video_id"] = doc.video_id
    return chunk_transcript(SEGMENTS, chunk_size=40, chunk_overlap=8, video_metadata=meta)


def _legacy_chunks(key: str, n: int = 3) -> None:
    """Chunks named by nothing but their id, ``{key}:{n}``: no ``document_id``,
    ``video_id`` or ``source_id`` metadata to find them by."""
    chroma_service.get_global_collection().upsert(
        ids=[f"{key}:{i}" for i in range(n)],
        documents=[f"{WORDS}, legacy {i}." for i in range(n)],
        metadatas=[{"chunk_index": i} for i in range(n)],
    )


@pytest.fixture
def library(db, monkeypatch, ephemeral_chroma):
    from tests import conftest as _conftest

    monkeypatch.setattr(cef, "SessionLocal", _conftest.TestingSessionLocal)
    cached = json.dumps(SEGMENTS)
    docs = {
        # Flagged, with chunks.
        "ok": _document(db, "video", "vidFLAGOK001", flagged=True, cache=cached, video=True),
        "legacy_video": _document(db, "video", "vidLEGACY001", flagged=True, cache=cached, video=True),
        "legacy_podcast": _document(db, "podcast", "https://feeds.example/ep/7", flagged=True),
        # Flagged, no chunks.
        "video": _document(db, "video", "vidSTRAND001", flagged=True, cache=cached, video=True),
        "reddit": _document(db, "reddit", "t3_stranded", flagged=True, cache=cached),
        "pdf": _document(db, "pdf", "pdf:feedface", flagged=True),
        "hn": _document(db, "hn", "hn:4242", flagged=True, cache="{not json"),
        "article": _document(db, "article", "article:cafe", flagged=True),
        "empty": _document(db, "video", "vidEMPTY0001", flagged=True, video=True,
                           cache=json.dumps([{"text": "  ", "start": 0.0, "duration": 1.0}])),
        # Not flagged.
        "unflagged_chunks": _document(db, "video", "vidUNFLAG001", flagged=False, cache=cached, video=True),
        "unflagged_none": _document(db, "video", "vidNOTHING01", flagged=False, video=True),
    }
    db.commit()
    chroma_service.insert_chunks(
        _chunks_for(docs["ok"]) + _chunks_for(docs["unflagged_chunks"])
        + _chunks_for(Document(document_id="gone-document", source_type="video", source_id="vidGONE00001",
                               video_id="vidGONE00001", title="Deleted"))
    )
    _legacy_chunks("vidLEGACY001")
    _legacy_chunks(docs["legacy_podcast"].document_id)
    return {name: doc.document_id for name, doc in docs.items()}


def _flags(db) -> dict[str, bool]:
    db.expire_all()
    return {d.document_id: d.embedded_in_chroma for d in db.query(Document)}


def _chunk_ids() -> list[str]:
    return sorted(chroma_service.get_global_collection().get(include=[])["ids"])


def _run(tmp_path, *args: str) -> tuple[int, dict]:
    out = tmp_path / f"report-{len(list(tmp_path.iterdir()))}.json"
    code = cef.main([*args, "--page-size", "4", "--json", str(out)])
    return code, json.loads(out.read_text(encoding="utf-8"))


def _found(report: dict, bucket: str) -> list[str]:
    return sorted(row["document_id"] for row in report["found"][bucket])


# ---------------------------------------------------------------- the dry run


def test_the_dry_run_counts_by_source_type_and_by_where_the_text_lives(library, db, tmp_path, capsys):
    flags, chunks = _flags(db), _chunk_ids()

    code, report = _run(tmp_path)

    assert code == 0 and report["write"] is False and not report["stopped"]
    assert _flags(db) == flags and _chunk_ids() == chunks, "a dry run changes nothing"
    assert report["collection"] == "pratidhvani_global"
    assert report["chunks_scanned"] == len(chunks)
    assert report["chunks_of_no_document"] == len(_chunks_for(Document(
        document_id="x", source_type="video", source_id="x", video_id="x", title="x")))
    assert (report["flagged"], report["flagged_with_chunks"], report["without_chunks"]) == (9, 3, 6)
    assert report["unflagged_with_chunks"] == 1
    assert report["by_source"] == {
        "article": {"flagged": 1, "fetch_again": 1},
        "hn": {"flagged": 1, "fetch_again": 1},
        "pdf": {"flagged": 1, "fetch_again": 1},
        "podcast": {"flagged": 1, "with_chunks": 1},
        "reddit": {"flagged": 1, "cached": 1},
        "video": {"flagged": 4, "with_chunks": 2, "cached": 1, "empty": 1},
    }
    assert _found(report, "cached") == sorted([library["video"], library["reddit"]])
    assert _found(report, "fetch_again") == sorted([library["pdf"], library["hn"], library["article"]])
    assert _found(report, "empty") == [library["empty"]]
    assert report["to_clear"] == 5 and report["cleared"] == 0

    out = capsys.readouterr().out
    assert "dry run" in out and "would clear 5 flag(s)" in out
    for name in ("video", "reddit", "pdf", "hn", "article", "empty"):
        assert library[name] in out, "every document found is named by its id"
    assert "vidSTRAND001" in out
    assert WORDS not in out and "must not print" not in out, "ids and counts, never text"


def test_chunks_named_only_by_their_id_count_as_embedded(library, tmp_path):
    _, report = _run(tmp_path)

    found = {row["document_id"] for rows in report["found"].values() for row in rows}
    assert library["legacy_video"] not in found, "{video_id}:{n}"
    assert library["legacy_podcast"] not in found, "{document_id}:{n}"


def test_mutation_a_check_that_ignores_chunk_ids_would_unflag_the_legacy_documents(library, tmp_path, monkeypatch):
    monkeypatch.setattr(embedded_flag_service, "_owner_of_chunk_id", lambda chunk_id, index: "")

    _, report = _run(tmp_path)

    assert library["legacy_video"] in _found(report, "cached")
    assert library["legacy_podcast"] in _found(report, "fetch_again")
    assert report["to_clear"] == 7


def test_the_recheck_before_the_write_also_reads_chunk_ids(library, db, tmp_path, monkeypatch):
    """The second line: with the scan's id reading broken, the per-document
    re-check still finds ``{key}:0`` and keeps both flags."""
    monkeypatch.setattr(embedded_flag_service, "_owner_of_chunk_id", lambda chunk_id, index: "")

    _, report = _run(tmp_path, "--write")

    assert report["kept_on_recheck"] == 2 and report["cleared"] == 5
    flags = _flags(db)
    assert flags[library["legacy_video"]] and flags[library["legacy_podcast"]]


def test_the_dry_run_cannot_write_and_leaves_the_connection_as_it_found_it(library, db, monkeypatch):
    """``PRAGMA query_only``: a bug in the dry run fails rather than writes."""

    def tries_to_write(session, **kwargs):
        session.execute(text("UPDATE documents SET embedded_in_chroma = 0"))
        return embedded_flag_service.FlagCheckReport(write=False)

    monkeypatch.setattr(cef.embedded_flag_service, "check_embedded_flags", tries_to_write)
    with pytest.raises(OperationalError, match="readonly"):
        cef.main([])
    db.execute(text("UPDATE documents SET embedded_in_chroma = embedded_in_chroma"))


# ---------------------------------------------------------------- --write


def test_write_clears_exactly_the_flagged_documents_without_chunks(library, db, tmp_path, capsys):
    before, chunks = _flags(db), _chunk_ids()

    code, report = _run(tmp_path, "--write")

    assert code == 0 and report["cleared"] == 5 and report["kept_on_recheck"] == 0
    cleared = {library[n] for n in ("video", "reddit", "pdf", "hn", "article")}
    assert _flags(db) == {did: (False if did in cleared else flag) for did, flag in before.items()}
    assert _chunk_ids() == chunks, "nothing in Chroma changes"
    assert "cleared 5 flag(s)" in capsys.readouterr().out

    code, again = _run(tmp_path, "--write")
    assert code == 0 and again["to_clear"] == 0 and again["cleared"] == 0, "a second run finds nothing"
    assert _found(again, "empty") == [library["empty"]], "still reported, still flagged"


def test_document_ids_narrow_the_check(library, db, tmp_path):
    before = _flags(db)

    _, report = _run(tmp_path, "--write", "--document-ids", f"{library['reddit']},{library['ok']}")

    assert report["flagged"] == 2 and report["cleared"] == 1
    assert _flags(db) == {**before, library["reddit"]: False}


def test_a_document_embedded_since_the_scan_keeps_its_flag(library, db, tmp_path, monkeypatch):
    """A job that inserts a document's chunks between the scan and the write."""
    real_scan = embedded_flag_service._scan_chunks

    def scan_then_a_job_embeds(*args):
        stopped = real_scan(*args)
        db.expire_all()
        chroma_service.insert_chunks(_chunks_for(db.get(Document, library["video"])))
        return stopped

    monkeypatch.setattr(embedded_flag_service, "_scan_chunks", scan_then_a_job_embeds)

    _, report = _run(tmp_path, "--write")

    assert report["kept_on_recheck"] == 1 and report["cleared"] == 4
    assert _flags(db)[library["video"]] is True


def test_a_scan_that_stops_part_way_writes_nothing(library, db, tmp_path, monkeypatch):
    """A partial scan would count every document on the unread pages chunkless."""
    real_open = embedded_flag_service._open_collection

    class FailsOnPageTwo:
        def __init__(self, collection):
            self._collection = collection

        def get(self, **kwargs):
            if kwargs.get("offset"):
                raise RuntimeError("chroma went away")
            return self._collection.get(**kwargs)

    monkeypatch.setattr(embedded_flag_service, "_open_collection", lambda: FailsOnPageTwo(real_open()))
    before = _flags(db)

    code, report = _run(tmp_path, "--write")

    assert code == 1 and "scan failed" in report["stopped"]
    assert report["cleared"] == 0 and report["without_chunks"] == 0
    assert _flags(db) == before


def test_a_store_that_belongs_to_another_database_writes_nothing(library, db, tmp_path, monkeypatch):
    """The wrong DATABASE_URL or CHROMA_PERSIST_DIR: no chunk names a document
    here, so every flagged document would look chunkless."""
    other = chroma_service.get_chroma_client().create_collection("another_install", embedding_function=None)
    other.add(ids=["vidELSEWHERE:0"], embeddings=[[0.1, 0.2]], documents=["x"],
              metadatas=[{"document_id": "someone-elses-document", "chunk_index": 0}])
    monkeypatch.setattr(embedded_flag_service.settings, "CHROMA_GLOBAL_COLLECTION_NAME", "another_install")
    before = _flags(db)

    code, report = _run(tmp_path, "--write")

    assert code == 1 and "DATABASE_URL" in report["stopped"]
    assert report["without_chunks"] == 9 and report["cleared"] == 0
    assert _flags(db) == before


def test_a_missing_collection_is_neither_created_nor_cleared_against(library, db, tmp_path, monkeypatch):
    monkeypatch.setattr(embedded_flag_service.settings, "CHROMA_GLOBAL_COLLECTION_NAME", "no_such_collection")
    before = _flags(db)

    code, report = _run(tmp_path, "--write")

    assert code == 1 and "could not open the collection no_such_collection" in report["stopped"]
    assert _flags(db) == before
    names = [c.name for c in chroma_service.get_chroma_client().list_collections()]
    assert "no_such_collection" not in names


# ---------------------------------------------------------------- the next job embeds what --write cleared


class _FakeConnector:
    """Every connector call a run can make, recorded and answered offline."""

    def __init__(self):
        self.fetched: list[str] = []

    def resolve_creator_id(self, value, job_id=""):
        return CHANNEL

    def fetch_creator(self, creator_id, job_id=""):
        return CreatorMetadata(creator_external_id=creator_id, name="Flag Channel",
                               extra={"uploads_playlist_id": "UUflagCheck00001"})

    def list_creator_items(self, creator_id, limit=10, job_id=""):
        return []

    def fetch_metadata(self, ids, job_id=""):
        return {}

    def fetch_text(self, candidate, **kwargs):
        self.fetched.append(candidate.source_id)
        return ExtractedText(segments=SEGMENTS, language="en", text_source="youtube", word_count=60)


@pytest.fixture
def worker(monkeypatch, library, tmp_path):
    """The task module on the test session, with every way out of a run faked:
    progress, the usage scope, the connectors, the uploads listing, the era
    call and the report. No network and no model."""
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    progress = MagicMock()
    monkeypatch.setattr(job_tasks, "progress_service", progress)
    monkeypatch.setattr("app.services.progress_service.publish_error", progress.publish_error)
    monkeypatch.setattr(job_tasks.usage_service, "metered", MagicMock(return_value=nullcontext()))
    connector = _FakeConnector()
    monkeypatch.setattr(job_tasks, "connector_for", lambda source_type: connector)
    monkeypatch.setattr(job_tasks.youtube_service, "get_channel_videos_all", MagicMock(return_value=[]))
    monkeypatch.setattr(temporal_service, "extract_discussed_era", lambda *a, **k: None)
    monkeypatch.setattr("app.agents.report_agent.run_report_agent",
                        MagicMock(return_value=({}, "<p>report</p>")))
    monkeypatch.setattr(job_tasks, "build_report_html", lambda **kwargs: "<html>report</html>")
    monkeypatch.setattr(job_tasks.settings, "REPORTS_DIR", str(tmp_path / "reports"))
    return SimpleNamespace(connector=connector)


def _next_job(db, kind: str, document_ids: list[str], tenant_id: str) -> str:
    """A later run whose selection includes the documents: a topic job after
    its approval, or a subscription sync whose links are already there."""
    if kind == "sync":
        db.add(Channel(channel_id=CHANNEL, name="Flag Channel", uploads_playlist_id="UUflagCheck00001"))
        job = Job(job_type="subscription", status="pending", topic="Sync Flag Channel",
                  channel_list=json.dumps([CHANNEL]), num_videos=0, tenant_id=tenant_id)
    else:
        job = Job(job_type="topic", topic="tidal power", status="extracting", tenant_id=tenant_id)
    db.add(job)
    db.flush()
    for document_id in document_ids:
        doc = db.get(Document, document_id)
        db.add(JobVideo(job_id=job.id, document_id=document_id, video_id=doc.video_id, approved=True,
                        selection_reason="subscription" if kind == "sync" else None))
    db.commit()
    (SYNC if kind == "sync" else RESUME).run(job.id)
    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    return job.id


def _document_chunks(document_id: str) -> list[str]:
    return chroma_service.get_global_collection().get(where={"document_id": document_id}, include=[])["ids"]


@pytest.mark.parametrize("kind", ["resume", "sync"])
def test_the_next_job_embeds_a_cleared_document_from_its_cache(library, worker, db, tmp_path, test_user, kind):
    stranded = [library["video"], library["reddit"]]
    if kind == "sync":
        stranded = [library["video"]]  # a sync walks one channel's videos

    code, _ = _run(tmp_path, "--write")
    assert code == 0
    _next_job(db, kind, stranded, test_user.id)

    for document_id in stranded:
        assert _document_chunks(document_id), "its chunks are in the library now"
        assert _flags(db)[document_id] is True, "and it is flagged so, once they are"
    assert worker.connector.fetched == [], "re-chunked from transcript_cache: nothing fetched"

    _, after = _run(tmp_path)
    assert not {row["document_id"] for row in after["found"]["cached"]} & set(stranded)


def test_mutation_without_the_write_the_next_job_inserts_nothing(library, worker, db, test_user):
    """The state the script repairs: flagged with cached text, the next job
    takes the document as fully reused and leaves it out of the library."""
    _next_job(db, "resume", [library["video"], library["reddit"]], test_user.id)

    assert _document_chunks(library["video"]) == [] and _document_chunks(library["reddit"]) == []
    assert worker.connector.fetched == []


def test_the_next_job_fetches_a_cleared_document_whose_text_lived_only_in_its_chunks(
    library, worker, db, tmp_path, test_user
):
    _run(tmp_path, "--write")

    _next_job(db, "resume", [library["hn"]], test_user.id)

    assert worker.connector.fetched == ["hn:4242"]
    assert _document_chunks(library["hn"]) and _flags(db)[library["hn"]] is True
