"""Test configuration and fixtures."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.in_memory_session import get_session_repository


@pytest.fixture(autouse=True)
async def reset_repository():
    """Ensure in-memory repository is clear before each test."""
    repo = get_session_repository()
    await repo.clear()
    yield
    await repo.clear()


@pytest.fixture
def client():
    """Provide a FastAPI TestClient."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
