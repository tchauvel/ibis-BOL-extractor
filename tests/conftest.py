"""
tests/conftest.py — Shared pytest fixtures and configuration.

Environment variables must be set BEFORE any app modules are imported, because
config.py reads them at module load time via pydantic-settings.
"""
import os

# Override settings for the test environment before importing any app code.
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")
os.environ.setdefault("RATE_LIMIT", "10000/minute")   # effectively unlimited in tests
os.environ.setdefault("LOG_FORMAT", "text")             # human-readable in test output

import pytest  # noqa: E402 — must come after env vars are set
from fastapi.testclient import TestClient

from api import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    """
    A TestClient that shares the app lifespan for the entire test session.
    Use `scope="session"` to avoid re-initialising the app on every test.
    """
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
