import os
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from shared.models import (
    Company,
    Contact,
    EmailAccount,
    EnrichedPerson,
    PersonSummary,
    Sequence,
)

logger = structlog.get_logger("apollo_client")


class ApolloRateLimitError(Exception):
    """Raised on HTTP 429 from Apollo."""


class ApolloApiError(Exception):
    """Raised on non-2xx responses from Apollo (excluding 429)."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Apollo API {status_code}: {detail}")


def _retry_on_429() -> Any:
    return retry(
        retry=retry_if_exception_type(ApolloRateLimitError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )


class ApolloClient:
    """Async Apollo.io API client with retry and Pydantic parsing."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ["APOLLO_API_KEY"]
        self.base_url = (
            base_url
            or os.environ.get("APOLLO_BASE_URL", "https://api.apollo.io/api/v1")
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"X-Api-Key": self.api_key},
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _handle_response(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 429:
            raise ApolloRateLimitError("Rate limited by Apollo")
        if resp.status_code >= 400:
            raise ApolloApiError(resp.status_code, resp.text)
        return resp.json()  # type: ignore[no-any-return]

    @_retry_on_429()
    async def _post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.post(path, json=json)
        return await self._handle_response(resp)

    @_retry_on_429()
    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(path, params=params)
        return await self._handle_response(resp)

    @_retry_on_429()
    async def _patch(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.patch(path, json=json)
        return await self._handle_response(resp)

    # ── Prospecting MCP endpoints ──

    async def search_people(
        self, filters: dict[str, Any], page: int = 1, per_page: int = 25
    ) -> tuple[list[PersonSummary], int]:
        """POST /mixed_people/api_search — no credit cost, no emails."""
        payload: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
        }
        if filters.get("titles"):
            payload["person_titles"] = filters["titles"]
        if filters.get("seniorities"):
            payload["person_seniorities"] = filters["seniorities"]
        if filters.get("person_locations"):
            payload["person_locations"] = filters["person_locations"]
        if filters.get("organization_locations"):
            payload["organization_locations"] = filters["organization_locations"]
        if filters.get("organization_domains"):
            payload["q_organization_domains"] = "\n".join(
                filters["organization_domains"]
            )
        if filters.get("organization_ids"):
            payload["organization_ids"] = filters["organization_ids"]
        if filters.get("employee_ranges"):
            payload["organization_num_employees_ranges"] = filters["employee_ranges"]
        if filters.get("technologies_any_of"):
            payload["currently_using_any_of_technology_uids"] = filters[
                "technologies_any_of"
            ]
        if filters.get("technologies_all_of"):
            payload["currently_using_all_of_technology_uids"] = filters[
                "technologies_all_of"
            ]
        if filters.get("keywords"):
            payload["q_keywords"] = filters["keywords"]

        data = await self._post("/mixed_people/api_search", json=payload)
        people = data.get("people", [])
        total = data.get("pagination", {}).get("total_entries", 0)
        results = [
            PersonSummary(
                id=p["id"],
                name=f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                title=p.get("title"),
                company=p.get("organization", {}).get("name") if p.get("organization") else None,
                company_domain=p.get("organization", {}).get("primary_domain") if p.get("organization") else None,
                linkedin_url=p.get("linkedin_url"),
                location=p.get("city"),
            )
            for p in people
        ]
        return results, total

    async def search_companies(
        self, filters: dict[str, Any], page: int = 1, per_page: int = 25
    ) -> tuple[list[Company], int]:
        """POST /mixed_companies/search."""
        payload: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
        }
        if filters.get("industries"):
            payload["organization_industry_tag_ids"] = filters["industries"]
        if filters.get("locations"):
            payload["organization_locations"] = filters["locations"]
        if filters.get("employee_ranges"):
            payload["organization_num_employees_ranges"] = filters["employee_ranges"]
        if filters.get("revenue_min") is not None or filters.get("revenue_max") is not None:
            revenue: dict[str, Any] = {}
            if filters.get("revenue_min") is not None:
                revenue["min"] = filters["revenue_min"]
            if filters.get("revenue_max") is not None:
                revenue["max"] = filters["revenue_max"]
            payload["organization_revenue_range"] = revenue
        if filters.get("technologies_any_of"):
            payload["currently_using_any_of_technology_uids"] = filters[
                "technologies_any_of"
            ]
        if filters.get("keywords"):
            payload["q_organization_keyword_tags"] = [filters["keywords"]]

        data = await self._post("/mixed_companies/search", json=payload)
        orgs = data.get("organizations", [])
        total = data.get("pagination", {}).get("total_entries", 0)
        results = [
            Company(
                id=o["id"],
                name=o.get("name", ""),
                domain=o.get("primary_domain"),
                industry=o.get("industry"),
                employee_count=o.get("estimated_num_employees"),
                employee_range=o.get("organization_num_employees_ranges"),
                revenue_range=o.get("organization_revenue_printed"),
                technologies=[
                    t.get("name", "") for t in (o.get("current_technologies") or [])
                ],
                linkedin_url=o.get("linkedin_url"),
                location=o.get("raw_address"),
            )
            for o in orgs
        ]
        return results, total

    async def enrich_people(
        self,
        person_ids: list[str],
        reveal_personal_emails: bool = True,
        reveal_phone_number: bool = False,
    ) -> list[EnrichedPerson]:
        """POST /people/bulk_match — costs credits."""
        details = [{"id": pid} for pid in person_ids]
        data = await self._post(
            "/people/bulk_match",
            json={
                "details": details,
                "reveal_personal_emails": reveal_personal_emails,
                "reveal_phone_number": reveal_phone_number,
            },
        )
        matches = data.get("matches", [])
        return [
            EnrichedPerson(
                id=m.get("id", ""),
                name=f"{m.get('first_name', '')} {m.get('last_name', '')}".strip(),
                title=m.get("title"),
                company=m.get("organization", {}).get("name") if m.get("organization") else None,
                company_domain=m.get("organization", {}).get("primary_domain") if m.get("organization") else None,
                linkedin_url=m.get("linkedin_url"),
                location=m.get("city"),
                email=m.get("email"),
                email_status=m.get("email_status"),
                phone=m.get("phone_number") if reveal_phone_number else None,
            )
            for m in matches
        ]

    async def enrich_company(self, domain: str) -> Company:
        """GET /organizations/enrich."""
        data = await self._get("/organizations/enrich", params={"domain": domain})
        org = data.get("organization", {})
        return Company(
            id=org.get("id", ""),
            name=org.get("name", ""),
            domain=org.get("primary_domain"),
            industry=org.get("industry"),
            employee_count=org.get("estimated_num_employees"),
            employee_range=org.get("organization_num_employees_ranges"),
            revenue_range=org.get("organization_revenue_printed"),
            technologies=[
                t.get("name", "") for t in (org.get("current_technologies") or [])
            ],
            linkedin_url=org.get("linkedin_url"),
            location=org.get("raw_address"),
        )

    async def get_job_postings(self, organization_id: str) -> list[dict[str, Any]]:
        """GET /organizations/{id}/job_postings."""
        data = await self._get(f"/organizations/{organization_id}/job_postings")
        return data.get("job_postings", [])  # type: ignore[no-any-return]

    # ── Sending MCP endpoints ──

    async def search_contacts(self, q_keywords: str) -> list[Contact]:
        """POST /contacts/search — find contacts by email or keyword."""
        data = await self._post(
            "/contacts/search",
            json={"q_keywords": q_keywords, "page": 1, "per_page": 10},
        )
        contacts = data.get("contacts", [])
        return [
            Contact(
                id=c["id"],
                email=c.get("email"),
                first_name=c.get("first_name"),
                last_name=c.get("last_name"),
                title=c.get("title"),
                company=c.get("organization_name"),
            )
            for c in contacts
        ]

    async def create_contact(
        self,
        email: str,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> Contact:
        """POST /contacts with run_dedupe=true."""
        payload: dict[str, Any] = {"email": email, "run_dedupe": True}
        if first_name:
            payload["first_name"] = first_name
        if last_name:
            payload["last_name"] = last_name
        data = await self._post("/contacts", json=payload)
        c = data.get("contact", {})
        return Contact(
            id=c["id"],
            email=c.get("email"),
            first_name=c.get("first_name"),
            last_name=c.get("last_name"),
            title=c.get("title"),
            company=c.get("organization_name"),
        )

    async def update_contact(
        self, contact_id: str, typed_custom_fields: dict[str, str]
    ) -> Contact:
        """PATCH /contacts/{id} — update custom fields."""
        data = await self._patch(
            f"/contacts/{contact_id}",
            json={"typed_custom_fields": typed_custom_fields},
        )
        c = data.get("contact", {})
        return Contact(
            id=c.get("id", contact_id),
            email=c.get("email"),
            first_name=c.get("first_name"),
            last_name=c.get("last_name"),
            title=c.get("title"),
            company=c.get("organization_name"),
        )

    async def search_sequences(self, q_name: str) -> list[Sequence]:
        """POST /emailer_campaigns/search — find sequences by name."""
        data = await self._post(
            "/emailer_campaigns/search",
            json={"q_name": q_name, "page": 1, "per_page": 10},
        )
        campaigns = data.get("emailer_campaigns", [])
        return [
            Sequence(
                id=s["id"],
                name=s.get("name", ""),
                active=s.get("active", False),
                num_steps=s.get("num_steps"),
            )
            for s in campaigns
        ]

    async def list_email_accounts(self) -> list[EmailAccount]:
        """GET /email_accounts."""
        data = await self._get("/email_accounts")
        accounts = data.get("email_accounts", [])
        return [
            EmailAccount(
                id=a["id"],
                email=a.get("email", ""),
                active=a.get("active", False),
                sender_name=a.get("sender_name"),
            )
            for a in accounts
        ]

    async def add_to_sequence(
        self,
        sequence_id: str,
        contact_ids: list[str],
        send_email_from_email_account_id: str,
        sequence_active_in_other_campaigns: bool = False,
        sequence_unverified_email: bool = False,
        sequence_state: str = "active",
        auto_unpause_at: str | None = None,
    ) -> dict[str, Any]:
        """POST /emailer_campaigns/{id}/add_contact_ids."""
        payload: dict[str, Any] = {
            "contact_ids": contact_ids,
            "emailer_campaign_id": sequence_id,
            "send_email_from_email_account_id": send_email_from_email_account_id,
            "sequence_active_in_other_campaigns": sequence_active_in_other_campaigns,
            "sequence_unverified_email": sequence_unverified_email,
            "sequence_state": sequence_state,
        }
        if auto_unpause_at:
            payload["auto_unpause_at"] = auto_unpause_at
        return await self._post(
            f"/emailer_campaigns/{sequence_id}/add_contact_ids",
            json=payload,
        )

    async def list_custom_fields(self) -> list[dict[str, Any]]:
        """GET /typed_custom_fields — list custom fields."""
        data = await self._get("/typed_custom_fields")
        return data.get("typed_custom_fields", [])  # type: ignore[no-any-return]

    async def search_contacts_filtered(
        self,
        sequence_id: str | None = None,
        last_contacted_after: str | None = None,
        last_contacted_before: str | None = None,
        page: int = 1,
        per_page: int = 25,
    ) -> tuple[list[dict[str, Any]], int]:
        """POST /contacts/search with filters for sequence and last-contacted date."""
        payload: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "sort_by_field": "contact_last_activity_date",
            "sort_ascending": False,
        }
        if sequence_id:
            payload["emailer_campaign_ids"] = [sequence_id]
        if last_contacted_after or last_contacted_before:
            date_range: dict[str, str] = {}
            if last_contacted_after:
                date_range["min"] = last_contacted_after
            if last_contacted_before:
                date_range["max"] = last_contacted_before
            payload["contact_last_activity_date_range"] = date_range

        data = await self._post("/contacts/search", json=payload)
        contacts = data.get("contacts", [])
        total = data.get("pagination", {}).get("total_entries", 0)
        results = [
            {
                "id": c.get("id"),
                "email": c.get("email"),
                "first_name": c.get("first_name"),
                "last_name": c.get("last_name"),
                "name": f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(),
                "title": c.get("title"),
                "company": c.get("organization_name"),
                "last_activity_date": c.get("contact_last_activity_date"),
                "emailer_campaign_ids": c.get("emailer_campaign_ids", []),
            }
            for c in contacts
        ]
        return results, total

    async def get_emailer_messages(
        self,
        contact_id: str,
        emailer_campaign_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """POST /emailer_messages/search — get email messages for a contact."""
        payload: dict[str, Any] = {
            "contact_id": contact_id,
            "page": 1,
            "per_page": 50,
        }
        if emailer_campaign_id:
            payload["emailer_campaign_id"] = emailer_campaign_id
        data = await self._post("/emailer_messages/search", json=payload)
        messages = data.get("emailer_messages", [])
        return [
            {
                "id": m.get("id"),
                "subject": m.get("subject"),
                "body_text": m.get("body_text"),
                "body_html": m.get("body_html"),
                "sent_at": m.get("sent_at"),
                "opened_at": m.get("opened_at"),
                "replied_at": m.get("replied_at"),
                "reply_body": m.get("reply_message", {}).get("body")
                if m.get("reply_message")
                else None,
                "reply_subject": m.get("reply_message", {}).get("subject")
                if m.get("reply_message")
                else None,
                "reply_received_at": m.get("reply_message", {}).get("created_at")
                if m.get("reply_message")
                else None,
                "status": m.get("status"),
            }
            for m in messages
        ]  # type: ignore[no-any-return]
