"""Integration test configuration — resets rate limiter state before each test."""

import pytest

from app.limiter import limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    """Reset the slowapi in-memory rate limit counters before every test.

    Without this, rate limit state accumulated in one test bleeds into the
    next, causing false 429s in unrelated tests.
    """
    limiter.reset()
