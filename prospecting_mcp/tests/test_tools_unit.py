"""Unit tests for prospecting MCP tools (mocked Apollo)."""

from unittest.mock import AsyncMock, patch

import pytest

from shared.models import Company, EnrichedPerson, PersonSummary

# Import the tool functions directly
from prospecting_mcp.server import (
    CompanyFilter,
    PersonFilter,
    enrich_company,
    enrich_people,
    get_company_job_postings,
    find_people_at_companies,
    list_contacts,
    search_companies,
    search_people,
)


def _mock_apollo() -> AsyncMock:
    mock = AsyncMock()
    mock.search_people.return_value = (
        [
            PersonSummary(
                id="p1",
                name="Jane Doe",
                title="VP Sales",
                company="Acme Corp",
                company_domain="acme.com",
                linkedin_url="https://linkedin.com/in/janedoe",
                location="Denver",
            )
        ],
        1,
    )
    mock.search_companies.return_value = (
        [
            Company(
                id="o1",
                name="Acme Corp",
                domain="acme.com",
                industry="Technology",
                employee_count=500,
                technologies=["Python"],
            )
        ],
        1,
    )
    mock.enrich_people.return_value = [
        EnrichedPerson(
            id="p1",
            name="Jane Doe",
            title="VP Sales",
            email="jane@acme.com",
            email_status="verified",
        )
    ]
    mock.enrich_company.return_value = Company(
        id="o1",
        name="Acme Corp",
        domain="acme.com",
        industry="Technology",
        employee_count=500,
        technologies=[],
    )
    mock.get_job_postings.return_value = [
        {"title": "Senior Engineer", "url": "https://jobs.acme.com/1"}
    ]
    mock.search_sequences.return_value = [
        __import__("shared.models", fromlist=["Sequence"]).Sequence(
            id="seq1", name="AI Bespoke Send", active=True, num_steps=1
        )
    ]
    mock.search_contacts_filtered.return_value = (
        [
            {
                "id": "c1",
                "email": "jane@acme.com",
                "first_name": "Jane",
                "last_name": "Doe",
                "name": "Jane Doe",
                "title": "VP Sales",
                "company": "Acme Corp",
                "last_activity_date": "2026-04-01T12:00:00Z",
                "emailer_campaign_ids": ["seq1"],
            }
        ],
        1,
    )
    return mock


@pytest.fixture(autouse=True)
def _patch_apollo():
    mock = _mock_apollo()
    with patch("prospecting_mcp.server._get_apollo", return_value=mock):
        yield mock


async def test_search_people(_patch_apollo: AsyncMock) -> None:
    results = await search_people(
        PersonFilter(titles=["VP Sales"], person_locations=["Denver, US"])
    )
    assert len(results) == 1
    assert results[0].name == "Jane Doe"
    _patch_apollo.search_people.assert_called_once()


async def test_search_companies(_patch_apollo: AsyncMock) -> None:
    results = await search_companies(CompanyFilter(keywords="technology"))
    assert len(results) == 1
    assert results[0]["name"] == "Acme Corp"
    _patch_apollo.search_companies.assert_called_once()


async def test_find_people_at_companies(_patch_apollo: AsyncMock) -> None:
    results = await find_people_at_companies(
        company_filters=CompanyFilter(keywords="technology"),
        person_filters=PersonFilter(titles=["VP Sales"]),
        max_companies=5,
        max_people_per_company=3,
    )
    assert len(results) >= 1
    assert results[0].name == "Jane Doe"


async def test_enrich_people(_patch_apollo: AsyncMock) -> None:
    results = await enrich_people(person_ids=["p1"], reveal_emails=True)
    assert len(results) == 1
    assert results[0].email == "jane@acme.com"
    assert results[0].email_status == "verified"


async def test_enrich_people_max_10() -> None:
    with pytest.raises(ValueError, match="10 IDs per call"):
        await enrich_people(person_ids=[f"p{i}" for i in range(11)])


async def test_enrich_company(_patch_apollo: AsyncMock) -> None:
    result = await enrich_company(domain="acme.com")
    assert result["name"] == "Acme Corp"
    _patch_apollo.enrich_company.assert_called_once_with(domain="acme.com")


async def test_get_company_job_postings(_patch_apollo: AsyncMock) -> None:
    results = await get_company_job_postings(organization_id="o1")
    assert len(results) == 1
    assert results[0]["title"] == "Senior Engineer"


async def test_list_contacts_by_sequence(_patch_apollo: AsyncMock) -> None:
    result = await list_contacts(sequence_name="AI Bespoke Send")
    assert result["total"] == 1
    assert len(result["contacts"]) == 1
    assert result["contacts"][0]["email"] == "jane@acme.com"
    _patch_apollo.search_sequences.assert_called_once()
    _patch_apollo.search_contacts_filtered.assert_called_once()


async def test_list_contacts_by_date(_patch_apollo: AsyncMock) -> None:
    result = await list_contacts(last_contacted_after="2026-01-01")
    assert result["total"] == 1
    _patch_apollo.search_contacts_filtered.assert_called_once_with(
        sequence_id=None,
        last_contacted_after="2026-01-01",
        last_contacted_before=None,
        page=1,
        per_page=25,
    )


async def test_list_contacts_sequence_not_found(_patch_apollo: AsyncMock) -> None:
    _patch_apollo.search_sequences.return_value = []
    result = await list_contacts(sequence_name="Nonexistent")
    assert "error" in result
    assert result["total"] == 0
