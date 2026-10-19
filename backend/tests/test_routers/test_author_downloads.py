"""S-6.7.2 — binary artifacts and downloads.

A throwaway outputter for the `deck` kind writes a binary artifact through
`output_artifacts.write_artifact`, standing in for the PPTX/PDF/EPUB
outputters that come later; the book exercises the text path.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import settings
from app.models.job import Job
from app.models.output import Output
from app.services import auth_service, output_artifacts, output_service
from app.services.output_service import OutputError

PPTX = output_artifacts.FORMATS["pptx"]


class _FakeDeck:
    kind = "deck"

    def __init__(self, *, fail: bool = False, cancel_mid: bool = False):
        self.fail = fail
        self.cancel_mid = cancel_mid

    def generate(self, db, user, output):
        output_artifacts.write_artifact(output, "pptx", b"PK\x03\x04 fake deck bytes")
        if self.cancel_mid:
            db.query(Output).filter(Output.id == output.id).update({"status": "cancelled"})
            db.commit()
            output_service.report_progress(db, output, 50, "slide 3")
        if self.fail:
            raise OutputError("renderer exploded")


@pytest.fixture(autouse=True)
def outputs_dir(tmp_path, monkeypatch):
    root = tmp_path / "outputs"
    monkeypatch.setattr(settings, "OUTPUTS_DIR", str(root))
    with patch("app.services.progress_service.publish_progress"), patch("app.services.progress_service.publish_status_change"):
        yield root


@pytest.fixture
def fake_deck():
    original = output_service._OUTPUTTERS.get("deck")
    outputter = _FakeDeck()
    output_service.register_outputter(outputter)
    yield outputter
    if original is None:
        output_service._OUTPUTTERS.pop("deck", None)
    else:
        output_service.register_outputter(original)


def _pro(db, email):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


def _deck(client, headers, title="Rate cuts deck"):
    r = client.post("/api/v1/author/outputs?sync=true", headers=headers,
                    json={"kind": "deck", "title": title, "source_ids": ["job-x"]})
    assert r.status_code == 200, r.text
    return r.json()


def test_binary_artifact_downloads_with_its_media_type(unauthenticated_client, db, fake_deck, outputs_dir):
    user, headers = _pro(db, "d1@x.com")
    out = _deck(unauthenticated_client, headers)
    assert out["status"] == "completed" and out["has_content"] is True
    assert out["formats"] == ["pptx"]

    row = db.get(Output, out["id"])
    assert row.content_path == f"{user.id}/{row.id}/artifact.pptx"
    assert (outputs_dir / row.content_path).is_file()

    r = unauthenticated_client.get(f"/api/v1/author/outputs/{out['id']}/download", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == PPTX
    assert r.content == b"PK\x03\x04 fake deck bytes"
    assert 'attachment; filename="rate-cuts-deck.pptx"' in r.headers["content-disposition"]


def test_book_text_and_extra_formats(unauthenticated_client, db, monkeypatch):
    from app.services import report_service

    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<h1>T</h1><p>Body.</p>")
    user, headers = _pro(db, "d2@x.com")
    job = Job(id=str(uuid.uuid4()), tenant_id=user.id, job_type="topic", status="completed", topic="T", report_path="/r.html")
    db.add(job)
    db.commit()
    out = unauthenticated_client.post("/api/v1/author/outputs?sync=true", headers=headers,
                                      json={"kind": "book", "title": "My Book", "source_ids": [job.id]}).json()
    assert out["formats"] == ["md"]

    r = unauthenticated_client.get(f"/api/v1/author/outputs/{out['id']}/download", headers=headers)
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.text.startswith("# My Book")
    assert 'filename="my-book.md"' in r.headers["content-disposition"]

    # A later outputter (S-6.1.5) adds a PDF beside the Markdown.
    row = db.get(Output, out["id"])
    output_artifacts.write_artifact(row, "pdf", b"%PDF-1.7 fake", primary=False)
    listed = unauthenticated_client.get(f"/api/v1/author/outputs/{out['id']}", headers=headers).json()
    assert listed["formats"] == ["md", "pdf"]
    r = unauthenticated_client.get(f"/api/v1/author/outputs/{out['id']}/download", params={"format": "pdf"}, headers=headers)
    assert r.headers["content-type"] == "application/pdf" and r.content == b"%PDF-1.7 fake"


def test_missing_format_and_bad_format(unauthenticated_client, db, fake_deck):
    _, headers = _pro(db, "d3@x.com")
    out = _deck(unauthenticated_client, headers)
    r = unauthenticated_client.get(f"/api/v1/author/outputs/{out['id']}/download", params={"format": "pdf"}, headers=headers)
    assert r.status_code == 404 and "available" in r.json()["detail"]
    for bad in ("../x", "PDF!", "a" * 20):
        r = unauthenticated_client.get(f"/api/v1/author/outputs/{out['id']}/download", params={"format": bad}, headers=headers)
        assert r.status_code == 422, bad


def test_another_users_artifact_is_404(unauthenticated_client, db, fake_deck):
    _, headers_owner = _pro(db, "d4@x.com")
    _, headers_other = _pro(db, "d5@x.com")
    out = _deck(unauthenticated_client, headers_owner)
    r = unauthenticated_client.get(f"/api/v1/author/outputs/{out['id']}/download", headers=headers_other)
    assert r.status_code == 404
    assert b"fake deck" not in r.content


def test_download_requires_a_header_token(unauthenticated_client, db, fake_deck):
    user, headers = _pro(db, "d6@x.com")
    out = _deck(unauthenticated_client, headers)
    token = headers["Authorization"].split()[1]
    r = unauthenticated_client.get(f"/api/v1/author/outputs/{out['id']}/download", params={"token": token})
    assert r.status_code == 401


def test_delete_removes_the_artifact_directory(unauthenticated_client, db, fake_deck, outputs_dir):
    user, headers = _pro(db, "d7@x.com")
    out = _deck(unauthenticated_client, headers)
    directory = outputs_dir / user.id / out["id"]
    assert directory.is_dir()
    assert unauthenticated_client.delete(f"/api/v1/author/outputs/{out['id']}", headers=headers).status_code == 200
    assert not directory.exists()
    assert not (outputs_dir / user.id).exists(), "an empty user directory is removed too"


def test_a_tampered_content_path_is_never_served(unauthenticated_client, db, fake_deck, outputs_dir, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("host secret")
    _, headers = _pro(db, "d8@x.com")
    out = _deck(unauthenticated_client, headers)
    row = db.get(Output, out["id"])
    for tampered in ("../secret.txt", str(secret), "x/../../secret.txt"):
        row.content_path = tampered
        db.commit()
        assert output_artifacts.resolve_content_path(tampered) is None
        r = unauthenticated_client.get(f"/api/v1/author/outputs/{out['id']}/download", headers=headers)
        assert r.status_code == 200 and b"host secret" not in r.content  # served from the row's own directory


def test_unsafe_ids_never_become_paths(db):
    row = Output(id="../../etc", user_id="u", kind="deck", title="t")
    with pytest.raises(output_artifacts.ArtifactError):
        output_artifacts.output_dir(row)
    with pytest.raises(output_artifacts.ArtifactError):
        output_artifacts.write_artifact(row, "pptx", b"x")
    assert output_artifacts.available_formats(row) == []
    good = Output(id="abc", user_id="u", kind="deck", title="t")
    with pytest.raises(output_artifacts.ArtifactError):
        output_artifacts.artifact_file(good, "exe")


def test_cancel_and_failure_leave_no_files(db, outputs_dir):
    user = auth_service.create_user(db, email="d9@x.com", password="pw" * 6)
    original = output_service._OUTPUTTERS.get("deck")
    try:
        for outputter, expected in ((_FakeDeck(cancel_mid=True), "cancelled"), (_FakeDeck(fail=True), "failed")):
            output_service.register_outputter(outputter)
            row = output_service.create_output(db, user_id=user.id, kind="deck", title="t", source_ids=["j"])
            result = output_service.run_generation(db, user, row)
            assert result.status == expected
            assert result.content_path is None
            assert not (outputs_dir / user.id / row.id).exists(), expected
    finally:
        if original is None:
            output_service._OUTPUTTERS.pop("deck", None)
        else:
            output_service.register_outputter(original)


def test_orphan_sweep_lists_then_deletes(db, outputs_dir, capsys):
    from scripts import sweep_output_artifacts

    user = auth_service.create_user(db, email="d10@x.com", password="pw" * 6)
    kept = output_service.create_output(db, user_id=user.id, kind="deck", title="t", source_ids=["j"])
    output_artifacts.write_artifact(kept, "pptx", b"kept")
    db.commit()
    orphan = outputs_dir / user.id / "deleted-output-id"
    orphan.mkdir(parents=True)
    (orphan / "artifact.pdf").write_bytes(b"old")
    misfiled = outputs_dir / "someone-else" / kept.id
    misfiled.mkdir(parents=True)

    assert set(output_artifacts.find_orphans(db)) == {orphan, misfiled}
    with patch("scripts.sweep_output_artifacts.SessionLocal", return_value=db):
        sweep_output_artifacts.main([])
        assert orphan.exists(), "a dry run deletes nothing"
        sweep_output_artifacts.main(["--apply"])
    assert not orphan.exists() and not misfiled.exists()
    assert (outputs_dir / user.id / kept.id / "artifact.pptx").is_file()
    assert "deleting" in capsys.readouterr().out


def test_non_ascii_titles_keep_their_name(unauthenticated_client, db, fake_deck):
    _, headers = _pro(db, "d11@x.com")
    out = _deck(unauthenticated_client, headers, title="हिंदी पुस्तक — भाग १")
    r = unauthenticated_client.get(f"/api/v1/author/outputs/{out['id']}/download", headers=headers)
    disposition = r.headers["content-disposition"]
    assert 'filename="output.pptx"' in disposition
    assert "filename*=UTF-8''%E0%A4%B9%E0%A4%BF%E0%A4%82%E0%A4%A6%E0%A5%80" in disposition
    assert output_artifacts.download_filename("हिंदी पुस्तक — भाग १", "pptx") == "हिंदी-पुस्तक-भाग-१.pptx"
