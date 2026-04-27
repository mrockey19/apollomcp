"""Integration tests for prospecting MCP (real Apollo API).

Only run when RUN_INTEGRATION=1 is set and APOLLO_API_KEY is available.
"""

import os

import pytest

from prospecting_mcp.server import (
    PersonFilter,
    enrich_people,
    search_people,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Integration tests disabled (set RUN_INTEGRATION=1)",
)


async def test_search_and_enrich_real() -> None:
    """Search for CISOs in Denver, then enrich the first result."""
    results = await search_people(
        PersonFilter(titles=["CISO"], person_locations=["Denver, US"])
    )
    assert len(results) >= 1, "Expected at least one CISO in Denver"

    person_ids = [results[0].id]
    enriched = await enrich_people(person_ids=person_ids, reveal_emails=True)
    assert len(enriched) >= 1
    # At least check that we got an email field back (may be None if unavailable)
    assert hasattr(enriched[0], "email")
