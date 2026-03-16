"""
Shared pytest fixtures for OGLAP tests.
"""

from __future__ import annotations

import pytest

from oglap import init_oglap


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async tests."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def oglap_report():
    """Initialize OGLAP once for the entire test session (downloads/caches data)."""
    progress_log: list[dict] = []

    def on_progress(**kwargs):
        progress_log.append(kwargs)

    report = await init_oglap({"on_progress": on_progress})
    assert report["ok"], f"initOglap failed: {report.get('error')}"
    return report
