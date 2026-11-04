from pydantic import BaseModel


class LanguageMixView(BaseModel):
    """A document's measured language mix (T-1.16.1.7), read-only.

    Built by ``language_mix_service.public_view`` from
    ``documents.language_mix``; absent (null) until the document has been
    chunked since T-1.16.1.7 or profiled by ``scripts/backfill_language_mix.py``.
    Mirrors ``frontend/src/types/video.ts::LanguageMix``.

    - ``primary_language``: ``en``, ``hi`` (Hindi/Urdu in any script),
      ``other`` (a non-English language in another script; see
      ``native_script``) or ``none`` (no language-bearing words).
    - ``native_script``: the script the non-English words are written in
      (``Devanagari``, ``Bengali``...; ``Latin`` when romanised), or null.
    - ``hi_share``: non-English words over all language-bearing words.
    - ``matrix_hi_share``: share of speech framed by non-English grammar.
    - ``quote_mode``: ``plain_english`` / ``roman`` / ``native_script``.
    - ``code_mixed``: whether the chunks carry the ``code_mix_*`` fields,
      the chunker's own decision (3% presence floor), so a page labels a
      source as mixed exactly when the models are told it is.
    """

    primary_language: str
    native_script: str | None = None
    hi_share: float = 0.0
    matrix_hi_share: float = 0.0
    quote_mode: str | None = None
    code_mixed: bool = False
