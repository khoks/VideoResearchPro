"""What a library question is asked over (S-8.1.4).

Stored as ``library_qa_exchanges.scope_json``; saved searches (M3, S-8.3.2)
store the same shape on ``saved_searches.scope_json`` and stamp it on the
exchanges their runs produce. Read and write it through
``app.services.qa_scope_service`` (``dump`` / ``load`` / ``resolve_document_ids``),
never with ad-hoc ``json`` calls.

The shape is a small JSON object:

* **Absent / null** — the whole library: every document the reader can see
  (D-063 / D-070). Every exchange written before the column existed reads so.
* **Narrowing keys** intersect with that visible set; they never widen it, and
  a scope that resolves to no documents retrieves nothing.
  - ``shelf_id``: the documents selected by the runs on one of the reader's
    shelves (M1).
* **Provenance keys** record where an exchange came from and never change
  what it retrieves.
  - ``saved_search_id``: produced by a saved search's run (M3).

Keys are added, never repurposed. Reading keeps keys this build does not know
(``extra="allow"``), so an older build never drops what a newer one wrote;
resolving refuses a key it does not know, because ignoring an unknown narrowing
key would silently widen the question to the whole library.

Examples: ``null`` · ``{"shelf_id": "…"}`` · ``{"saved_search_id": "…"}`` ·
``{"saved_search_id": "…", "shelf_id": "…"}``.
"""
from pydantic import BaseModel, ConfigDict


class QAScope(BaseModel):
    model_config = ConfigDict(extra="allow")

    shelf_id: str | None = None
    saved_search_id: str | None = None
