# Apollo.io API Reference

## Base URL

`https://api.apollo.io/api/v1`

## Authentication

All requests require header: `X-Api-Key: <master_key>`

Most write endpoints (sequences, custom fields, bulk ops) require a **master API key** or return 403.

## Key Endpoints

### People Search (no credit cost)
- `POST /mixed_people/api_search`
- Returns IDs only — no emails

### People Enrichment (costs credits)
- `POST /people/bulk_match` with `reveal_personal_emails=true`
- Max 10 IDs per call

### Company Search
- `POST /mixed_companies/search`

### Company Enrichment
- `GET /organizations/enrich?domain=example.com`

### Job Postings
- `GET /organizations/{id}/job_postings`

### Contacts
- `POST /contacts/search` — find by email/keyword
- `POST /contacts` — create (with `run_dedupe=true`)
- `PATCH /contacts/{id}` — update custom fields

### Sequences
- `POST /emailer_campaigns/search` — find by name
- `POST /emailer_campaigns/{id}/add_contact_ids` — enroll contacts
- **Cannot create sequences via API** — must use Apollo UI

### Email Accounts
- `GET /email_accounts` — list connected mailboxes

### Custom Fields
- `GET /typed_custom_fields` — list all custom fields

## Rate Limits

- Per-tier limits visible at `POST /usage_stats/api_usage_stats`
- 429 responses are retryable with exponential backoff (max 3 retries)

## Pagination

- Max 100 per page, 500 pages = 50,000 records per query
- Build narrowing filters to stay under limits

## Lists

"Lists" are labels. Pass `label_names[]` on contact create/update; the list materializes if it doesn't exist.
