"""S-6.2.1 — the static personal-wiki site.

The acceptance: a user picks a shelf, generates a site, downloads a zip, opens
``index.html`` from disk and can read every report, search by title and
follow citations; the site has no app chrome and makes no network calls
except to sources. Underneath: every link inside the zip resolves (files and
fragments), the only absolute links go to sources, shelves and runs resolve
inside the caller's own library, and each source page lists the reports that
cite it.
"""
from __future__ import annotations

import io
import json
import posixpath
import re
import zipfile
from urllib.parse import unquote, urlsplit

import pytest
from lxml import html as lxml_html

from app.models.document import Document
from app.models.output import Output
from app.models.output_citation import OutputCitation
from app.models.qa_exchange import QAExchange
from app.models.shelf import Shelf
from app.models.shelf_job import ShelfJob
from app.models.tag import Tag
from app.models.tagging import Tagging
from app.services import auth_service, output_artifacts, output_service
from tests.test_services.test_book_endnotes import _smoke_run

SOURCE_HOSTS = ("www.youtube.com", "youtube.com", "youtu.be")


@pytest.fixture(autouse=True)
def _outputs(tmp_path, monkeypatch):
    import app.services.outputters  # noqa: F401

    monkeypatch.setattr("app.config.settings.OUTPUTS_DIR", str(tmp_path / "outputs"))
    from unittest.mock import patch

    with patch("app.services.progress_service.publish_progress"), patch("app.services.progress_service.publish_status_change"):
        yield


def _site(db, user, source_ids, title="My wiki"):
    row = output_service.create_output(db, user_id=user.id, kind="site", title=title, source_ids=source_ids)
    return output_service.run_generation(db, user, row)


def _files(out) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(output_artifacts.artifact_file(out, "zip").read_bytes())) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def _assert_self_contained(files: dict[str, bytes]) -> list[str]:
    """Every relative link resolves to a file in the zip (and to an id, when
    it has a fragment); absolute links go only to sources; nothing is loaded
    from outside. Returns the external links."""
    docs = {n: lxml_html.fromstring(b) for n, b in files.items() if n.endswith(".html")}
    ids = {n: set(d.xpath("//@id")) for n, d in docs.items()}
    external: list[str] = []
    for name, doc in docs.items():
        for el, attr in [(e, "href") for e in doc.xpath("//*[@href]")] + [(e, "src") for e in doc.xpath("//*[@src]")]:
            target = el.get(attr)
            parts = urlsplit(target)
            if parts.scheme in ("http", "https"):
                assert el.tag == "a", f"{name}: {el.tag} loads {target} from the network"
                assert parts.hostname in SOURCE_HOSTS, f"{name}: link to a non-source host {target}"
                external.append(target)
                continue
            assert not parts.scheme and not target.startswith("/"), f"{name}: absolute app link {target}"
            path = unquote(parts.path)
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), path)) if path else name
            assert resolved in files, f"{name}: {target} -> missing {resolved}"
            if parts.fragment and resolved.endswith(".html"):
                assert unquote(parts.fragment) in ids[resolved], f"{name}: {target} -> missing #{parts.fragment}"
    return external


def test_a_shelf_becomes_a_self_contained_site(db, tmp_path):
    user = auth_service.create_user(db, email="site@x.com", password="pw" * 6)
    a = _smoke_run(db, user.id, tmp_path, topic="Smoking and lungs")
    b = _smoke_run(db, user.id, tmp_path, topic="हिंदी रिपोर्ट: रक्तचाप")
    shelf = Shelf(tenant_id=user.id, name="Health")
    db.add(shelf)
    db.commit()
    db.add_all([ShelfJob(shelf_id=shelf.id, job_id=a.id), ShelfJob(shelf_id=shelf.id, job_id=b.id)])
    doc_id = db.query(Document.document_id).first()[0]
    tag = Tag(tenant_id=user.id, name="lungs")
    db.add(tag)
    db.commit()
    db.add(Tagging(tag_id=tag.id, tenant_id=user.id, target_type="document", target_id=doc_id))
    db.add(QAExchange(job_id=a.id, tenant_id=user.id, question="Is smoking the main cause?", answer="Yes, per the talk.", references="[]"))
    db.commit()

    out = _site(db, user, [f"shelf:{shelf.id}"])
    assert out.status == "completed", out.error_message
    assert output_artifacts.available_formats(out) == ["md", "zip"]
    files = _files(out)
    names = sorted(files)
    assert names[0] == "about.html" and "index.html" in names and "search.html" in names
    assert all(re.fullmatch(r"[a-z0-9./-]+", n) for n in names), f"ASCII file names: {names}"

    reports = [n for n in names if n.startswith("reports/")]
    sources = [n for n in names if n.startswith("sources/")]
    assert len(reports) == 2 and len(sources) == 3
    assert any(n.startswith("tags/") for n in names)

    external = _assert_self_contained(files)
    assert external, "citations link out to the sources"

    index = files["index.html"].decode("utf-8")
    assert "Smoking and lungs" in index and "हिंदी रिपोर्ट: रक्तचाप" in index
    report = next(files[n].decode("utf-8") for n in reports if "smoking" in n)
    assert "Is smoking the main cause?" in report, "the run's Q&A is on its page"
    assert "/api/" not in "".join(f.decode("utf-8", "ignore") for f in files.values())

    # Backlinks: a source page lists the reports that cite it, with moments.
    page = lxml_html.fromstring(files[sources[0]])
    cited_in = page.xpath("//h2[@id='cited-in']/following-sibling::ul[1]/li/a[1]/@href")
    assert cited_in and all(h.startswith("../reports/") for h in cited_in)

    # Search: the index is a script that lists every report and source.
    js = files["assets/search-index.js"].decode("utf-8")
    entries = json.loads(js[js.index("=") + 1 : js.rindex(";")])
    assert {e["u"] for e in entries} >= set(reports) | set(sources)
    assert b"fetch(" not in files["assets/search.js"]

    rows = db.query(OutputCitation).filter(OutputCitation.output_id == out.id).count()
    assert rows == 60, "every citation on every report page is recorded"


def test_another_users_shelf_and_run_are_left_out_and_said_so(db, tmp_path):
    me = auth_service.create_user(db, email="site-me@x.com", password="pw" * 6)
    other = auth_service.create_user(db, email="site-other@x.com", password="pw" * 6)
    mine = _smoke_run(db, me.id, tmp_path, topic="Mine")
    theirs = _smoke_run(db, other.id, tmp_path, topic="Theirs")
    their_shelf = Shelf(tenant_id=other.id, name="Private")
    db.add(their_shelf)
    db.commit()
    out = _site(db, me, [f"job:{mine.id}", f"job:{theirs.id}", f"shelf:{their_shelf.id}"])
    assert out.status == "completed"
    files = _files(out)
    everything = b"".join(files.values()).decode("utf-8", "ignore")
    assert "Theirs" not in everything and "Private" not in everything
    assert "is not in your library and was left out" in files["about.html"].decode("utf-8")


def test_nothing_publishable_fails_with_the_reason(db, tmp_path):
    user = auth_service.create_user(db, email="site-none@x.com", password="pw" * 6)
    out = _site(db, user, ["job:nope", "shelf:nope"])
    assert out.status == "failed" and "Nothing to publish" in out.error_message
    assert output_artifacts.available_formats(out) == []


def test_kinds_lists_site(unauthenticated_client, db):
    user = auth_service.create_user(db, email="site-kinds@x.com", password="pw" * 6)
    user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    body = unauthenticated_client.get("/api/v1/author/kinds", headers={"Authorization": f"Bearer {token}"}).json()
    assert "site" in body["available"]
    assert db.query(Output).count() == 0
