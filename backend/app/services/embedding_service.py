"""Multilingual sentence-transformer embedding service.

Pratidhvani indexes transcripts that may be spoken in Hindi, Urdu,
English, Russian, or code-mixed across these languages. To embed such
content into a shared RAG index we use ``paraphrase-multilingual-MiniLM-L12-v2``
— a 384-dim multilingual sentence-transformer that is a drop-in replacement
for the default English ``all-MiniLM-L6-v2``. The model supports 50+
languages at comparable quality.

Why multilingual matters here:

* Whisper auto-detects the spoken language and transcribes natively via
  OpenAI's ``audio.transcriptions.create`` endpoint, so proper nouns stay
  in their original script (Devanagari, Cyrillic, Perso-Arabic, etc.).
* Code-mixed audio (e.g. Hindi-English) is captured as-is without being
  translated to English.
* Using a multilingual embedder means a Hindi transcript chunk and an
  English question land in a similar vector region, so cross-lingual
  retrieval works without translating queries or content.
* Proper nouns in non-Latin scripts are embedded semantically close to
  their English/transliterated counterparts.

The Q&A agent is responsible for choosing the answer language downstream
via a prompt-level instruction; this module is concerned only with
producing the embeddings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Module-level singleton. Loaded lazily on first use because the
# SentenceTransformer constructor downloads model weights on first run
# (~120 MB) and takes a few seconds to initialize.
_model: "SentenceTransformer | None" = None


def get_embedding_model() -> "SentenceTransformer":
    """Return the process-wide multilingual sentence-transformer.

    The model is loaded lazily on first call and reused thereafter.
    """
    global _model
    if _model is None:
        # Import here so that merely importing this module does not
        # trigger the heavy sentence-transformers import chain.
        from sentence_transformers import SentenceTransformer

        logger.info(
            "Loading sentence-transformer model %r (this may download weights on first run)",
            settings.EMBEDDING_MODEL_NAME,
        )
        _model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        logger.info("Sentence-transformer model %r ready", settings.EMBEDDING_MODEL_NAME)
    return _model


def encode(texts: list[str]) -> list[list[float]]:
    """Encode a batch of texts into embedding vectors.

    Args:
        texts: List of input strings (any language).

    Returns:
        List of embedding vectors (lists of floats). Each vector has
        384 dimensions for ``paraphrase-multilingual-MiniLM-L12-v2``.
    """
    if not texts:
        return []
    model = get_embedding_model()
    vectors = model.encode(list(texts), show_progress_bar=False)
    # ``encode`` returns a numpy ndarray by default; normalize to plain lists
    # so callers (e.g. Chroma metadata filters, JSON serialization) don't
    # need to know about numpy.
    return [list(map(float, v)) for v in vectors]
