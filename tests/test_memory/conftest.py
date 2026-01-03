"""Pytest fixtures for mcp_memory tests."""

import pytest


@pytest.fixture(scope="session")
def embedding_model():
    """Load the sentence transformer model once for all tests.

    This is a session-scoped fixture to avoid reloading the model
    for each test, which is very slow (especially in CI).
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("all-MiniLM-L6-v2")
