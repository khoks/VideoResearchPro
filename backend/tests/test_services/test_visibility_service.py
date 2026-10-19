"""``visibility_service`` keyed on ``document_id`` (D-070)."""
from app.models.document import Document
from app.services import visibility_service


def _docs(db):
    vid = Document(document_id="doc-video", video_id="yt0000000001", title="v", url="u")
    pdf = Document(document_id="doc-pdf", source_type="pdf", source_id="pdf:x", title="p", url="u")
    db.add_all([vid, pdf])
    db.commit()
    return vid, pdf


def test_grant_is_keyed_on_document_id_for_every_source_type(db, test_user):
    vid, pdf = _docs(db)
    # The exact call the PDF and paste paths make — a no-op before D-070
    # because `pdf.video_id` is None.
    assert visibility_service.grant(db, [pdf.document_id], test_user.id, visibility_service.SOURCE_PDF) == 1
    assert visibility_service.grant(db, [vid.document_id], test_user.id) == 1
    visible = {row[0] for row in visibility_service.visible_document_ids(db, test_user.id)}
    assert visible == {"doc-video", "doc-pdf"}


def test_grant_is_idempotent_and_drops_blank_ids(db, test_user):
    vid, _ = _docs(db)
    assert visibility_service.grant(db, [vid.document_id, vid.document_id, None, ""], test_user.id) == 1
    assert visibility_service.grant(db, [vid.document_id], test_user.id) == 0
    assert visibility_service.grant(db, [], test_user.id) == 0
    assert visibility_service.grant(db, [vid.document_id], None) == 0


def test_visible_set_is_per_tenant(db, test_user):
    vid, pdf = _docs(db)
    visibility_service.grant(db, [vid.document_id], test_user.id)
    visibility_service.grant(db, [pdf.document_id], "someone-else")
    assert {r[0] for r in visibility_service.visible_document_ids(db, test_user.id)} == {"doc-video"}
    assert {r[0] for r in visibility_service.visible_document_ids(db, "someone-else")} == {"doc-pdf"}
    assert visibility_service.visible_document_ids(db, "nobody").all() == []
