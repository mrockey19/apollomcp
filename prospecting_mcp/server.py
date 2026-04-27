from __future__ import annotations

import os
from typing import Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field
from starlette.middleware import Middleware

from shared.apollo_client import ApolloClient
from shared.auth import McpAuthMiddleware
from shared.logging import setup_logging

setup_logging()

mcp = FastMCP("apollo-prospecting")

# ── Models ──


class PersonFilter(BaseModel):
    titles: list[str] | None = Field(None, description="Job titles, e.g. ['VP Sales']")
    seniorities: list[
        Literal[
            "owner",
            "founder",
            "c_suite",
            "partner",
            "vp",
            "head",
            "director",
            "manager",
            "senior",
            "entry",
            "intern",
        ]
    ] | None = None
    person_locations: list[str] | None = None
    organization_locations: list[str] | None = None
    organization_domains: list[str] | None = None
    organization_ids: list[str] | None = None
    employee_ranges: list[str] | None = Field(
        None, description="e.g. ['1,10', '250,500']"
    )
    technologies_any_of: list[str] | None = None
    technologies_all_of: list[str] | None = None
    keywords: str | None = None
    page: int = 1
    per_page: int = 25


class CompanyFilter(BaseModel):
    industries: list[str] | None = None
    locations: list[str] | None = None
    employee_ranges: list[str] | None = None
    revenue_min: int | None = None
    revenue_max: int | None = None
    technologies_any_of: list[str] | None = None
    keywords: str | None = None
    page: int = 1
    per_page: int = 25


class PersonSummary(BaseModel):
    id: str
    name: str
    title: str | None = None
    company: str | None = None
    company_domain: str | None = None
    linkedin_url: str | None = None
    location: str | None = None


class EnrichedPerson(PersonSummary):
    email: str | None = None
    email_status: (
        Literal["verified", "unverified", "likely_to_engage", "unavailable"] | None
    ) = None
    phone: str | None = None


# ── Shared client instance ──

_apollo: ApolloClient | None = None


def _get_apollo() -> ApolloClient:
    global _apollo
    if _apollo is None:
        _apollo = ApolloClient()
    return _apollo


# ── Tools ──


@mcp.tool
async def search_people(filters: PersonFilter) -> list[PersonSummary]:
    """Find prospects in Apollo's database matching the given filters.

    Does NOT return emails. Call enrich_people to reveal emails for the IDs you care about.
    Costs no Apollo credits. Capped at 50,000 records per filter combination.
    """
    apollo = _get_apollo()
    results, _ = await apollo.search_people(
        filters=filters.model_dump(exclude_none=True),
        page=filters.page,
        per_page=filters.per_page,
    )
    return [PersonSummary.model_validate(r.model_dump()) for r in results]


@mcp.tool
async def search_companies(filters: CompanyFilter) -> list[dict]:
    """Find companies matching firmographic + technographic filters.

    Returns company id, name, domain, industry, headcount range, revenue range, tech stack.
    Consumes Apollo credits.
    """
    apollo = _get_apollo()
    results, _ = await apollo.search_companies(
        filters=filters.model_dump(exclude_none=True),
        page=filters.page,
        per_page=filters.per_page,
    )
    return [r.model_dump() for r in results]


@mcp.tool
async def find_people_at_companies(
    company_filters: CompanyFilter,
    person_filters: PersonFilter,
    max_companies: int = 25,
    max_people_per_company: int = 5,
) -> list[PersonSummary]:
    """Two-step convenience: search companies, then find people at those companies
    matching person_filters. Returns flat list of people."""
    apollo = _get_apollo()

    companies, _ = await apollo.search_companies(
        filters=company_filters.model_dump(exclude_none=True),
        page=1,
        per_page=min(max_companies, 25),
    )

    all_people: list[PersonSummary] = []
    for company in companies[:max_companies]:
        person_dict = person_filters.model_dump(exclude_none=True)
        person_dict["organization_ids"] = [company.id]
        results, _ = await apollo.search_people(
            filters=person_dict,
            page=1,
            per_page=max_people_per_company,
        )
        all_people.extend(
            PersonSummary.model_validate(r.model_dump()) for r in results
        )

    return all_people


@mcp.tool
async def enrich_people(
    person_ids: list[str],
    reveal_emails: bool = True,
    reveal_phones: bool = False,
) -> list[EnrichedPerson]:
    """Bulk-enrich up to 10 person IDs from search_people. Reveals emails (and optionally
    phones). This is where Apollo credits get spent."""
    if len(person_ids) > 10:
        raise ValueError(
            "Apollo's bulk enrichment caps at 10 IDs per call. Chunk in the agent."
        )
    apollo = _get_apollo()
    results = await apollo.enrich_people(
        person_ids=person_ids,
        reveal_personal_emails=reveal_emails,
        reveal_phone_number=reveal_phones,
    )
    return [EnrichedPerson.model_validate(r.model_dump()) for r in results]


@mcp.tool
async def enrich_company(domain: str) -> dict:
    """Enrich a single company by domain. Returns full firmographic profile."""
    apollo = _get_apollo()
    result = await apollo.enrich_company(domain=domain)
    return result.model_dump()


@mcp.tool
async def get_company_job_postings(organization_id: str) -> list[dict]:
    """Active job postings at a company. Useful as a buying-intent signal."""
    apollo = _get_apollo()
    return await apollo.get_job_postings(organization_id)


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        stateless_http=True,
        middleware=[Middleware(McpAuthMiddleware)],
    )
