"""Shared test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
async def _close_httpx_client():
    """Close the shared httpx AsyncClient after each test to prevent
    event-loop-leak errors across async tests."""
    yield
    from app.fetch import close_client

    await close_client()
