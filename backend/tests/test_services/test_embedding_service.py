import math
import os

import pytest

from app.config import settings
from app.services import embedding_service


@pytest.fixture(autouse=True)
def reset_singleton():
    """Each test starts with a fresh (unloaded) embedding model singleton."""
    embedding_service._model = None
    yield
    embedding_service._model = None


@pytest.mark.skipif(
    os.getenv("OFFLINE"),
    reason="needs multilingual sentence-transformer weights to be downloadable",
)
def test_encode_multilingual_returns_finite_384_dim_vectors():
    """A Hindi string and an English string should both embed cleanly into
    the expected 384-dim multilingual space."""
    vectors = embedding_service.encode(["hello", "नमस्ते"])
    assert len(vectors) == 2
    for v in vectors:
        assert len(v) == 384
        assert all(math.isfinite(x) for x in v)


@pytest.mark.skipif(
    os.getenv("OFFLINE"),
    reason="needs multilingual sentence-transformer weights to be downloadable",
)
def test_encode_empty_input_short_circuits():
    """encode([]) must not load the model."""
    assert embedding_service.encode([]) == []
    assert embedding_service._model is None


@pytest.mark.skipif(
    os.getenv("OFFLINE"),
    reason="needs multilingual sentence-transformer weights to be downloadable",
)
def test_get_embedding_model_is_singleton():
    model_a = embedding_service.get_embedding_model()
    model_b = embedding_service.get_embedding_model()
    assert model_a is model_b


def test_settings_default_embedding_model_is_multilingual():
    """Guard-rail: the configured default must be the multilingual model."""
    assert settings.EMBEDDING_MODEL_NAME == "paraphrase-multilingual-MiniLM-L12-v2"
