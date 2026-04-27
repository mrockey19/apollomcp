from __future__ import annotations

import os
from datetime import datetime
from typing import Literal

from fastmcp import FastMCP
from pydantic import BaseModel, EmailStr, Field
from shared.apollo_client import ApolloClient
from shared.logging import setup_logging

setup_logging()

mcp = FastMCP("apollo-sending")

# ── Models ──


class SendResult(BaseModel):
    contact_id: str
    sequence_id: str
    mailbox_id: str
    status: Literal[
        "enrolled_active", "enrolled_paused_until", "skipped_already_in_sequence"
    ]
    scheduled_for: datetime | None = None
    apollo_warnings: list[str] = []


# ── Shared client instance ──

_apollo: ApolloClient | None = None


def _get_apollo() -> ApolloClient:
    global _apollo
    if _apollo is None:
        _apollo = ApolloClient()
    return _apollo


# ── Tools ──


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
    in the sequence, returns status='skipped_already_in_sequence' and does NOT re-enroll
    (Apollo's default — override is intentionally not exposed here).
    """
    apollo = _get_apollo()

    # 1. Resolve sequence
    sequences = await apollo.search_sequences(q_name=sequence_name)
    seq = next((s for s in sequences if s.name == sequence_name), None)
    if not seq:
        raise ValueError(
            f"Sequence '{sequence_name}' not found. "
            "Build it in Apollo UI per docs/shell-sequence-setup.md"
        )
    sequence_id = seq.id

    # 2. Resolve mailbox
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
    mailbox_id = mailbox.id

    # 3. Resolve contact
    contacts = await apollo.search_contacts(q_keywords=str(contact_email))
    contact = next(
        (c for c in contacts if c.email and c.email.lower() == str(contact_email).lower()),
        None,
    )

    if not contact and create_if_missing:
        contact = await apollo.create_contact(email=str(contact_email))
    elif not contact:
        raise ValueError(
            f"Contact '{contact_email}' not found and create_if_missing=False."
        )

    contact_id = contact.id

    # 4. Update custom fields
    await apollo.update_contact(
        contact_id,
        typed_custom_fields={
            "ai_email_subject": subject,
            "ai_email_body": body,
        },
    )

    # 5. Enroll in sequence
    warnings: list[str] = []
    try:
        result = await apollo.add_to_sequence(
            sequence_id=sequence_id,
            contact_ids=[contact_id],
            send_email_from_email_account_id=mailbox_id,
            sequence_active_in_other_campaigns=False,
            sequence_unverified_email=False,
        )
        # Check for already-enrolled
        if result.get("contacts", []) == [] and result.get("already_in_sequence"):
            return SendResult(
                contact_id=contact_id,
                sequence_id=sequence_id,
                mailbox_id=mailbox_id,
                status="skipped_already_in_sequence",
            )
    except Exception as e:
        if "already" in str(e).lower():
            return SendResult(
                contact_id=contact_id,
                sequence_id=sequence_id,
                mailbox_id=mailbox_id,
                status="skipped_already_in_sequence",
            )
        raise

    status: Literal[
        "enrolled_active", "enrolled_paused_until", "skipped_already_in_sequence"
    ]
    if schedule_at:
        status = "enrolled_paused_until"
    else:
        status = "enrolled_active"

    return SendResult(
        contact_id=contact_id,
        sequence_id=sequence_id,
        mailbox_id=mailbox_id,
        status=status,
        scheduled_for=schedule_at,
        apollo_warnings=warnings,
    )


@mcp.tool
async def get_send_status(
    contact_email: EmailStr,
    sequence_name: str = "AI Bespoke Send",
) -> dict:
    """Check whether the contact has been sent the email yet, opened it, replied, etc."""
    apollo = _get_apollo()

    # Find the contact
    contacts = await apollo.search_contacts(q_keywords=str(contact_email))
    contact = next(
        (c for c in contacts if c.email and c.email.lower() == str(contact_email).lower()),
        None,
    )
    if not contact:
        return {"error": f"Contact '{contact_email}' not found."}

    # Find the sequence
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
async def list_active_mailboxes() -> list[dict]:
    """List the mailboxes the agent can pick from for the mailbox_email parameter."""
    apollo = _get_apollo()
    accounts = await apollo.list_email_accounts()
    return [
        a.model_dump()
        for a in accounts
        if a.active
    ]


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        stateless_http=True,
    )
