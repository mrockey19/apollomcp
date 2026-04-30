"""Unit tests for sending MCP tools (mocked Apollo)."""

from unittest.mock import AsyncMock, patch

import pytest

from shared.models import Contact, EmailAccount, Sequence

from sending_mcp.server import (
    get_replies,
    get_send_status,
    list_active_mailboxes,
    send_personalized_email,
)


def _mock_apollo() -> AsyncMock:
    mock = AsyncMock()
    mock.search_sequences.return_value = [
        Sequence(id="seq1", name="AI Bespoke Send", active=True, num_steps=1)
    ]
    mock.list_email_accounts.return_value = [
        EmailAccount(
            id="ea1",
            email="michael@rockeyvolunteer.com",
            active=True,
            sender_name="Michael",
        )
    ]
    mock.search_contacts.return_value = [
        Contact(
            id="c1",
            email="jane@acme.com",
            first_name="Jane",
            last_name="Doe",
            title="VP Sales",
        )
    ]
    mock.update_contact.return_value = Contact(
        id="c1", email="jane@acme.com", first_name="Jane"
    )
    mock.add_to_sequence.return_value = {
        "contacts": [{"id": "c1"}],
    }
    mock.create_contact.return_value = Contact(
        id="c_new", email="new@example.com", first_name="New"
    )
    mock.get_emailer_messages.return_value = [
        {
            "id": "msg1",
            "subject": "Quick test from the MCP",
            "body_text": "This is the body.",
            "sent_at": "2026-04-25T10:00:00Z",
            "opened_at": "2026-04-25T11:00:00Z",
            "replied_at": "2026-04-25T12:00:00Z",
            "reply_body": "Thanks for reaching out! Let's chat next week.",
            "reply_subject": "Re: Quick test from the MCP",
            "reply_received_at": "2026-04-25T12:00:00Z",
            "status": "replied",
        },
        {
            "id": "msg2",
            "subject": "Follow up",
            "body_text": "Just checking in.",
            "sent_at": "2026-04-26T10:00:00Z",
            "opened_at": None,
            "replied_at": None,
            "reply_body": None,
            "reply_subject": None,
            "reply_received_at": None,
            "status": "sent",
        },
    ]
    return mock


@pytest.fixture(autouse=True)
def _patch_apollo():
    mock = _mock_apollo()
    with patch("sending_mcp.server._get_apollo", return_value=mock):
        yield mock


async def test_send_personalized_email(_patch_apollo: AsyncMock) -> None:
    result = await send_personalized_email(
        contact_email="jane@acme.com",
        subject="Test Subject",
        body="Test body content",
    )
    assert result.status == "enrolled_active"
    assert result.contact_id == "c1"
    assert result.sequence_id == "seq1"
    assert result.mailbox_id == "ea1"
    _patch_apollo.update_contact.assert_called_once()
    _patch_apollo.add_to_sequence.assert_called_once()


async def test_send_creates_contact_if_missing(_patch_apollo: AsyncMock) -> None:
    _patch_apollo.search_contacts.return_value = []
    result = await send_personalized_email(
        contact_email="new@example.com",
        subject="Hello",
        body="Welcome!",
        create_if_missing=True,
    )
    assert result.contact_id == "c_new"
    _patch_apollo.create_contact.assert_called_once()


async def test_send_fails_without_create(_patch_apollo: AsyncMock) -> None:
    _patch_apollo.search_contacts.return_value = []
    with pytest.raises(ValueError, match="not found and create_if_missing=False"):
        await send_personalized_email(
            contact_email="missing@example.com",
            subject="Hello",
            body="Body",
            create_if_missing=False,
        )


async def test_send_sequence_not_found(_patch_apollo: AsyncMock) -> None:
    _patch_apollo.search_sequences.return_value = []
    with pytest.raises(ValueError, match="Sequence.*not found"):
        await send_personalized_email(
            contact_email="jane@acme.com",
            subject="Test",
            body="Body",
        )


async def test_send_with_specific_mailbox(_patch_apollo: AsyncMock) -> None:
    result = await send_personalized_email(
        contact_email="jane@acme.com",
        subject="Test",
        body="Body",
        mailbox_email="michael@rockeyvolunteer.com",
    )
    assert result.mailbox_id == "ea1"


async def test_send_wrong_mailbox(_patch_apollo: AsyncMock) -> None:
    with pytest.raises(ValueError, match="not found or not active"):
        await send_personalized_email(
            contact_email="jane@acme.com",
            subject="Test",
            body="Body",
            mailbox_email="nonexistent@example.com",
        )


async def test_get_send_status(_patch_apollo: AsyncMock) -> None:
    result = await get_send_status(contact_email="jane@acme.com")
    assert result["contact_id"] == "c1"
    assert result["sequence_id"] == "seq1"


async def test_get_send_status_contact_not_found(_patch_apollo: AsyncMock) -> None:
    _patch_apollo.search_contacts.return_value = []
    result = await get_send_status(contact_email="missing@example.com")
    assert "error" in result


async def test_get_replies_with_reply(_patch_apollo: AsyncMock) -> None:
    results = await get_replies(contact_email="jane@acme.com")
    assert len(results) == 1
    assert results[0]["reply_body"] == "Thanks for reaching out! Let's chat next week."
    assert results[0]["original_subject"] == "Quick test from the MCP"


async def test_get_replies_no_replies(_patch_apollo: AsyncMock) -> None:
    _patch_apollo.get_emailer_messages.return_value = [
        {
            "id": "msg2",
            "subject": "Follow up",
            "sent_at": "2026-04-26T10:00:00Z",
            "reply_body": None,
            "status": "sent",
        },
    ]
    results = await get_replies(contact_email="jane@acme.com")
    assert len(results) == 1
    assert "info" in results[0]
    assert results[0]["messages_checked"] == 1


async def test_get_replies_contact_not_found(_patch_apollo: AsyncMock) -> None:
    _patch_apollo.search_contacts.return_value = []
    results = await get_replies(contact_email="missing@example.com")
    assert "error" in results[0]


async def test_list_active_mailboxes(_patch_apollo: AsyncMock) -> None:
    results = await list_active_mailboxes()
    assert len(results) == 1
    assert results[0]["email"] == "michael@rockeyvolunteer.com"
    assert results[0]["active"] is True
