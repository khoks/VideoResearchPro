from pydantic import BaseModel, Field

# The documented meaning of `code_mixed`, also served in the OpenAPI schema.
CODE_MIXED_DESCRIPTION = (
    "Whether the measured text is not plain English by the chunker's 3% rule "
    "(code_mixing_service.chunk_metadata_from_profile): a property of the "
    "document's words, not of its stored chunks. A document chunked before "
    "S-1.16.2 and profiled since (scripts/backfill_language_mix.py, or a job "
    "that reused its existing chunks) can read true while its chunks carry no "
    "code_mix_* fields, so the models are not told its language mix until it "
    "is re-chunked."
)


class LanguageMixView(BaseModel):
    """A document's measured language mix (T-1.16.1.7), read-only.

    Built by ``language_mix_service.public_view`` from
    ``documents.language_mix``; absent (null) until the document has been
    chunked since T-1.16.1.7 or profiled by ``scripts/backfill_language_mix.py``.
    Mirrors ``frontend/src/types/video.ts::LanguageMix``.

    - ``primary_language``: ``en``, ``hi`` (Hindi/Urdu in any script),
      ``other`` (a non-English language in another script, see
      ``native_script``, or in Latin script with no Hindi evidence: the tagger
      cannot name it) or ``none`` (no language-bearing words).
    - ``native_script``: the script the non-English words are written in
      (``Devanagari``, ``Bengali``...; ``Latin`` when romanised), or null.
    - ``hi_share``: non-English words over all language-bearing words.
    - ``named_share``: of those words, the share the tagger could name; the
      rest it abstained on. Null when there are none, or on a profile stored
      before T-1.16.2.15.
    - ``matrix_hi_share``: share of speech framed by non-English grammar.
    - ``quote_mode``: ``plain_english`` / ``roman`` / ``native_script``.
    - ``code_mixed``: whether the measured TEXT is not plain English by the
      chunker's own rule (3% presence floor). It describes the words, not
      the stored chunks: a document chunked before S-1.16.2 and profiled
      since (the backfill, or a job that reused its chunks without
      re-embedding) can read true while its chunks carry no ``code_mix_*``
      fields until it is re-chunked. See ``CODE_MIXED_DESCRIPTION``.
    """

    primary_language: str
    native_script: str | None = None
    hi_share: float = 0.0
    named_share: float | None = None
    matrix_hi_share: float = 0.0
    quote_mode: str | None = None
    code_mixed: bool = Field(False, description=CODE_MIXED_DESCRIPTION)
