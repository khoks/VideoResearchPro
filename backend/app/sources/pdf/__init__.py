"""PDF source-type connector — registers under ``source_type='pdf'``.

Closes the **M-1.8 (PDF / e-book end-to-end)** milestone. PDFs are
the first source type with no discovery surface — they come from
user upload directly. The connector's `search()` and
`list_creator_items()` raise `NotImplementedError`, which per
[D-026](../../../docs/decisions.md#d-026--sequential-fan-out-for-the-connector-dispatcher-2026-05-02)
the orchestrator's `dispatch_search` already handles (treats as zero
candidates, not an error).

The connector exists primarily to plug into the polymorphic
plumbing — once a Document with `source_type='pdf'` is in the
library (via the upload endpoint), Q&A / report / library-wide
retrieval all flow through the standard pipeline. The connector's
load-bearing method is `fetch_text(candidate)`, which reads the
stored PDF bytes and runs them through PyMuPDF.

**Identity.**

- ``Candidate.source_id = f"pdf:{sha256_of_first_64kb}"``. We hash
  the first 64KB rather than the full file because (a) it's enough
  for collision avoidance in practice, (b) it's fast for very large
  PDFs (academic books, technical manuals), and (c) re-uploading
  the same file dedups even if the bytes differ slightly in trailer
  metadata.
- The raw bytes get persisted under ``PDF_UPLOAD_DIR/<source_id>.pdf``
  so a future PR can re-extract (e.g. with improved table extraction)
  without re-uploading.

**Per-page segment provenance.**

The flatten layer emits one segment per page with
``extra={"kind": "page", "page": <1-indexed>, ...}``. The chunker's
dominant-segment heuristic then promotes the dominant page's number
to chunk metadata as the equivalent of `comment_id`/`comment_url`
for reply-anchors — a citation can deep-link to the page where the
quoted text lives.

**Citation rendering.**

`<CitationLink>` displays PDFs as ``<title> · p. <page_number>`` and
clicks open the PDF file (the upload-served URL on backend) in the
user's PDF viewer. Modern viewers (Chrome's built-in, Firefox,
Adobe) honour ``#page=<N>`` URL fragments — we synthesise that
fragment in `comment_url` so per-page jumps work.
"""
