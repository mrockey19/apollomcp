import pytest
import respx
from httpx import Response

from shared.apollo_client import ApolloClient, ApolloApiError, ApolloRateLimitError


@pytest.fixture
def client() -> ApolloClient:
    return ApolloClient(api_key="test-key", base_url="https://api.apollo.io/api/v1")


@pytest.fixture(autouse=True)
async def _cleanup(client: ApolloClient):
    yield
    await client.close()


@respx.mock
async def test_search_people(client: ApolloClient) -> None:
    respx.post("https://api.apollo.io/api/v1/mixed_people/api_search").mock(
        return_value=Response(
            200,
            json={
                "people": [
                    {
                        "id": "p1",
                        "first_name": "Jane",
                        "last_name": "Doe",
                        "title": "VP Sales",
                        "organization": {
                            "name": "Acme Corp",
                            "primary_domain": "acme.com",
                        },
                        "linkedin_url": "https://linkedin.com/in/janedoe",
                        "city": "Denver",
                    }
                ],
                "pagination": {"total_entries": 1},
            },
        )
    )
    results, total = await client.search_people(
        filters={"titles": ["VP Sales"], "person_locations": ["Denver, US"]}
    )
    assert total == 1
    assert len(results) == 1
    assert results[0].name == "Jane Doe"
    assert results[0].title == "VP Sales"
    assert results[0].company == "Acme Corp"


@respx.mock
async def test_search_companies(client: ApolloClient) -> None:
    respx.post("https://api.apollo.io/api/v1/mixed_companies/search").mock(
        return_value=Response(
            200,
            json={
                "organizations": [
                    {
                        "id": "o1",
                        "name": "Acme Corp",
                        "primary_domain": "acme.com",
                        "industry": "Technology",
                        "estimated_num_employees": 500,
                        "organization_num_employees_ranges": "201-500",
                        "organization_revenue_printed": "$10M-$50M",
                        "current_technologies": [{"name": "Python"}],
                        "linkedin_url": "https://linkedin.com/company/acme",
                        "raw_address": "Denver, CO",
                    }
                ],
                "pagination": {"total_entries": 1},
            },
        )
    )
    results, total = await client.search_companies(
        filters={"keywords": "technology"}
    )
    assert total == 1
    assert results[0].name == "Acme Corp"
    assert results[0].domain == "acme.com"
    assert "Python" in results[0].technologies


@respx.mock
async def test_enrich_people(client: ApolloClient) -> None:
    respx.post("https://api.apollo.io/api/v1/people/bulk_match").mock(
        return_value=Response(
            200,
            json={
                "matches": [
                    {
                        "id": "p1",
                        "first_name": "Jane",
                        "last_name": "Doe",
                        "title": "VP Sales",
                        "organization": {
                            "name": "Acme Corp",
                            "primary_domain": "acme.com",
                        },
                        "linkedin_url": "https://linkedin.com/in/janedoe",
                        "city": "Denver",
                        "email": "jane@acme.com",
                        "email_status": "verified",
                    }
                ]
            },
        )
    )
    results = await client.enrich_people(person_ids=["p1"])
    assert len(results) == 1
    assert results[0].email == "jane@acme.com"
    assert results[0].email_status == "verified"


@respx.mock
async def test_enrich_company(client: ApolloClient) -> None:
    respx.get("https://api.apollo.io/api/v1/organizations/enrich").mock(
        return_value=Response(
            200,
            json={
                "organization": {
                    "id": "o1",
                    "name": "Acme Corp",
                    "primary_domain": "acme.com",
                    "industry": "Technology",
                    "estimated_num_employees": 500,
                    "current_technologies": [],
                }
            },
        )
    )
    result = await client.enrich_company(domain="acme.com")
    assert result.name == "Acme Corp"
    assert result.id == "o1"


@respx.mock
async def test_get_job_postings(client: ApolloClient) -> None:
    respx.get(
        "https://api.apollo.io/api/v1/organizations/o1/job_postings"
    ).mock(
        return_value=Response(
            200,
            json={
                "job_postings": [
                    {"title": "Senior Engineer", "url": "https://jobs.acme.com/1"}
                ]
            },
        )
    )
    results = await client.get_job_postings("o1")
    assert len(results) == 1
    assert results[0]["title"] == "Senior Engineer"


@respx.mock
async def test_search_contacts(client: ApolloClient) -> None:
    respx.post("https://api.apollo.io/api/v1/contacts/search").mock(
        return_value=Response(
            200,
            json={
                "contacts": [
                    {
                        "id": "c1",
                        "email": "jane@acme.com",
                        "first_name": "Jane",
                        "last_name": "Doe",
                        "title": "VP Sales",
                        "organization_name": "Acme Corp",
                    }
                ]
            },
        )
    )
    results = await client.search_contacts("jane@acme.com")
    assert len(results) == 1
    assert results[0].email == "jane@acme.com"


@respx.mock
async def test_create_contact(client: ApolloClient) -> None:
    respx.post("https://api.apollo.io/api/v1/contacts").mock(
        return_value=Response(
            200,
            json={
                "contact": {
                    "id": "c2",
                    "email": "new@example.com",
                    "first_name": "New",
                    "last_name": "Contact",
                }
            },
        )
    )
    result = await client.create_contact(email="new@example.com", first_name="New")
    assert result.id == "c2"
    assert result.email == "new@example.com"


@respx.mock
async def test_search_sequences(client: ApolloClient) -> None:
    respx.post("https://api.apollo.io/api/v1/emailer_campaigns/search").mock(
        return_value=Response(
            200,
            json={
                "emailer_campaigns": [
                    {
                        "id": "seq1",
                        "name": "AI Bespoke Send",
                        "active": True,
                        "num_steps": 1,
                    }
                ]
            },
        )
    )
    results = await client.search_sequences("AI Bespoke Send")
    assert len(results) == 1
    assert results[0].name == "AI Bespoke Send"
    assert results[0].active is True


@respx.mock
async def test_list_email_accounts(client: ApolloClient) -> None:
    respx.get("https://api.apollo.io/api/v1/email_accounts").mock(
        return_value=Response(
            200,
            json={
                "email_accounts": [
                    {
                        "id": "ea1",
                        "email": "michael@rockeyvolunteer.com",
                        "active": True,
                        "sender_name": "Michael",
                    }
                ]
            },
        )
    )
    results = await client.list_email_accounts()
    assert len(results) == 1
    assert results[0].email == "michael@rockeyvolunteer.com"
    assert results[0].active is True


@respx.mock
async def test_429_retry(client: ApolloClient) -> None:
    route = respx.post("https://api.apollo.io/api/v1/contacts/search")
    route.side_effect = [
        Response(429, text="Rate limited"),
        Response(
            200,
            json={"contacts": [{"id": "c1", "email": "test@test.com"}]},
        ),
    ]
    results = await client.search_contacts("test@test.com")
    assert len(results) == 1
    assert route.call_count == 2


@respx.mock
async def test_update_contact_resolves_field_ids(client: ApolloClient) -> None:
    """update_contact should resolve field names to Apollo field IDs."""
    respx.get("https://api.apollo.io/api/v1/typed_custom_fields").mock(
        return_value=Response(
            200,
            json={
                "typed_custom_fields": [
                    {"id": "tf_abc123", "name": "ai_email_subject"},
                    {"id": "tf_def456", "name": "ai_email_body"},
                ]
            },
        )
    )
    patch_route = respx.patch("https://api.apollo.io/api/v1/contacts/c1").mock(
        return_value=Response(
            200,
            json={
                "contact": {
                    "id": "c1",
                    "email": "jane@acme.com",
                    "first_name": "Jane",
                }
            },
        )
    )
    result = await client.update_contact(
        "c1",
        typed_custom_fields={
            "ai_email_subject": "Test Subject",
            "ai_email_body": "Test Body",
        },
    )
    assert result.id == "c1"
    # Verify the PATCH was called with field IDs, not names
    sent_json = patch_route.calls[0].request.content
    import json

    body = json.loads(sent_json)
    assert "tf_abc123" in body["typed_custom_fields"]
    assert "tf_def456" in body["typed_custom_fields"]
    assert body["typed_custom_fields"]["tf_abc123"] == "Test Subject"
    assert body["typed_custom_fields"]["tf_def456"] == "Test Body"


@respx.mock
async def test_update_contact_unknown_field(client: ApolloClient) -> None:
    """update_contact should raise ValueError for unknown field names."""
    respx.get("https://api.apollo.io/api/v1/typed_custom_fields").mock(
        return_value=Response(
            200,
            json={"typed_custom_fields": [{"id": "tf_abc123", "name": "ai_email_subject"}]},
        )
    )
    with pytest.raises(ValueError, match="Custom field 'nonexistent' not found"):
        await client.update_contact(
            "c1", typed_custom_fields={"nonexistent": "value"}
        )


@respx.mock
async def test_api_error(client: ApolloClient) -> None:
    respx.post("https://api.apollo.io/api/v1/contacts/search").mock(
        return_value=Response(403, text="Forbidden")
    )
    with pytest.raises(ApolloApiError) as exc_info:
        await client.search_contacts("test@test.com")
    assert exc_info.value.status_code == 403
