from __future__ import annotations

import os
from datetime import datetime
from typing import Literal

from fastmcp import FastMCP
from pydantic import BaseModel, EmailStr

from shared.apollo_client import ApolloClient
from shared.logging import setup_logging

setup_logging()

mcp = FastMCP("apollo-sending")


class SendResult(BaseModel):
    contact_id: str
    sequence_id: str
    mailbox_id: str
    status: Literal[
        "enrolled_active", "enrolled_paused_until", "skipped_already_in_sequence"
    ]
    scheduled_for: datetime | None = None


_apollo: ApolloClient | None = None


def _get_apollo() -> ApolloClient:
    global _apollo
    if _apollo is None:
        _apollo = ApolloClient()
    return _apollo


@mcp.tool
async def send_personalized_email(
    contact_email: EmailStr,
    subject: str,
    body: str,
    sequence_name: str = "AI Bespoke Send",
    mailbox_email: str | None = None,
    schedule_at: datetime | None = None,
    create_if_missing: bool = True,
) -> SendResult:
    """Send a fully bespoke email to one prospect.

    Mechanics: writes `subject` and `body` to the contact's `ai_email_subject` and
    `ai_email_body` custom fields, then enrolls the contact in the named shell sequence.
    Apollo handles deliverability, reply detection, unsubscribes.

    Returns a SendResult with the actual enrollment status. If the contact is already
    in the sequence, returns status='skipped_already_in_sequence' and does NOT re-enroll.
    """
    apollo = _get_apollo()
    email = str(contact_email).lower()

    sequences = await apollo.search_sequences(q_name=sequence_name)
    seq = next((s for s in sequences if s.name == sequence_name), None)
    if not seq:
        raise ValueError(
            f"Sequence '{sequence_name}' not found. "
            "Build it in Apollo UI per docs/shell-sequence-setup.md"
        )

    accounts = await apollo.list_email_accounts()
    active_accounts = [a for a in accounts if a.active]
    if not active_accounts:
        raise ValueError("No active mailboxes found in Apollo.")

    if mailbox_email:
        mailbox = next(
            (a for a in active_accounts if a.email == mailbox_email), None
        )
        if not mailbox:
            raise ValueError(
                f"Mailbox '{mailbox_email}' not found or not active. "
                f"Available: {[a.email for a in active_accounts]}"
            )
    else:
        mailbox = active_accounts[0]

    contacts = await apollo.search_contacts(q_keywords=email)
    contact = next(
        (c for c in contacts if c.email and c.email.lower() == email),
        None,
    )

    if not contact and create_if_missing:
        contact = await apollo.create_contact(email=email)
    elif not contact:
        raise ValueError(
            f"Contact '{email}' not found and create_if_missing=False."
        )

    await apollo.update_contact(
        contact.id,
        typed_custom_fields={
            "ai_email_subject": subject,
            "ai_email_body": body,
        },
    )

    try:
        result = await apollo.add_to_sequence(
            sequence_id=seq.id,
            contact_ids=[contact.id],
            send_email_from_email_account_id=mailbox.id,
            sequence_state="paused" if schedule_at else "active",
            auto_unpause_at=schedule_at.isoformat() if schedule_at else None,
        )
        if not result.get("contacts") and result.get("already_in_sequence"):
            return SendResult(
                contact_id=contact.id,
                sequence_id=seq.id,
                mailbox_id=mailbox.id,
                status="skipped_already_in_sequence",
            )
    except Exception as e:
        if "already" in str(e).lower():
            return SendResult(
                contact_id=contact.id,
                sequence_id=seq.id,
                mailbox_id=mailbox.id,
                status="skipped_already_in_sequence",
            )
        raise

    return SendResult(
        contact_id=contact.id,
        sequence_id=seq.id,
        mailbox_id=mailbox.id,
        status="enrolled_paused_until" if schedule_at else "enrolled_active",
        scheduled_for=schedule_at,
    )


@mcp.tool
async def get_send_status(
    contact_email: EmailStr,
    sequence_name: str = "AI Bespoke Send",
) -> dict:
    """Check whether the contact has been sent the email yet, opened it, replied, etc."""
    apollo = _get_apollo()
    email = str(contact_email).lower()

    contacts = await apollo.search_contacts(q_keywords=email)
    contact = next(
        (c for c in contacts if c.email and c.email.lower() == email),
        None,
    )
    if not contact:
        return {"error": f"Contact '{contact_email}' not found."}

    sequences = await apollo.search_sequences(q_name=sequence_name)
    seq = next((s for s in sequences if s.name == sequence_name), None)
    if not seq:
        return {"error": f"Sequence '{sequence_name}' not found."}

    return {
        "contact_id": contact.id,
        "contact_email": contact.email,
        "sequence_id": seq.id,
        "sequence_name": seq.name,
        "sequence_active": seq.active,
    }


@mcp.tool
async def get_replies(
    contact_email: EmailStr,
    sequence_name: str | None = None,
) -> list[dict]:
    """Get reply content for emails sent to a contact.

    Returns the full reply body, subject, and timestamp — not just a boolean.
    Use this to read what a prospect actually said so follow-ups can be context-aware.

    Args:
        contact_email: The prospect's email address.
        sequence_name: Optional — filter to replies from a specific sequence.
    """
    apollo = _get_apollo()

    contacts = await apollo.search_contacts(q_keywords=str(contact_email))
    contact = next(
        (c for c in contacts if c.email and c.email.lower() == str(contact_email).lower()),
        None,
    )
    if not contact:
        return [{"error": f"Contact '{contact_email}' not found."}]

    sequence_id: str | None = None
    if sequence_name:
        sequences = await apollo.search_sequences(q_name=sequence_name)
        seq = next((s for s in sequences if s.name == sequence_name), None)
        if seq:
            sequence_id = seq.id

    messages = await apollo.get_emailer_messages(
        contact_id=contact.id,
        emailer_campaign_id=sequence_id,
    )

    # Filter to only messages that have replies
    replies = [
        {
            "contact_email": str(contact_email),
            "original_subject": m.get("subject"),
            "sent_at": m.get("sent_at"),
            "reply_subject": m.get("reply_subject"),
            "reply_body": m.get("reply_body"),
            "reply_received_at": m.get("reply_received_at"),
        }
        for m in messages
        if m.get("reply_body")
    ]

    if not replies:
        return [{"info": f"No replies found from {contact_email}.", "messages_checked": len(messages)}]

    return replies


@mcp.tool
async def list_active_mailboxes() -> list[dict]:
    """List the mailboxes the agent can pick from for the mailbox_email parameter."""
    accounts = await _get_apollo().list_email_accounts()
    return [a.model_dump() for a in accounts if a.active]


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        stateless_http=True,
    )
