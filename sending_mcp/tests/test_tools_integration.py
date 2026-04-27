"""Integration tests for sending MCP (real Apollo API).

Only run when RUN_INTEGRATION=1 is set and APOLLO_API_KEY is available.
"""

import os

import pytest

from sending_mcp.server import list_active_mailboxes

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Integration tests disabled (set RUN_INTEGRATION=1)",
)


async def test_list_mailboxes_real() -> None:
    """Verify at least one active mailbox exists."""
    results = await list_active_mailboxes()
    assert len(results) >= 1, "Expected at least one active mailbox"
