# CLAUDE.md — Build Apollo Outreach MCP Stack

> **For Claude Code.** This is the build spec. Execute phase by phase. Do not skip phases. Each phase has a Definition of Done (DoD) — do not move forward until the DoD passes.

---

## 1. Mission

Build two production-grade MCP servers that wrap Apollo.io for an outreach agent stack:

1. **prospecting-mcp** — searches Apollo for people and companies that match filters, returns enriched contact data (incl. emails).
2. **sending-mcp** — sends a fully personalized, per-prospect email by enrolling that prospect into a pre-built Apollo sequence whose body is driven by custom fields.

Both run as **AWS Lambda container images** behind **Lambda Function URLs** using **FastMCP 2.x** in stateless HTTP mode and the **AWS Lambda Web Adapter**. Each MCP gets its own URL and is callable by any MCP client that supports streamable HTTP.

---

## 2. Operating principles

- Use `uv` for Python dependency management. Not pip + requirements.txt.
- Test locally before deploying. Every phase that touches code has a local test gate before the AWS gate.
- Idempotent infra: if Claude Code reruns a phase, it must not blow up working state. SAM stack updates, not deletes-then-creates.
- No secrets in code, repo, or Dockerfile. Apollo API key lives in **AWS Secrets Manager** only. Locally, `.env` is `.gitignore`'d.
- Default to typed Python (mypy-clean). Use Pydantic models for tool inputs/outputs. FastMCP picks up the schema automatically.
- When in doubt, ask the user before making an irreversible AWS change (deleting a stack, deleting a Lambda, deleting a secret).

---

## 3. Architecture decisions (locked — do not deviate without asking)

| Decision | Choice | Why |
|---|---|---|
| Language | Python 3.12 | FastMCP 2.x best support; matches Apollo SDK ecosystem |
| MCP framework | FastMCP 2.x (`fastmcp` on PyPI) | Stateless HTTP support; Pydantic-native schemas |
| Transport | Streamable HTTP, stateless mode | Compatible with serverless |
| Compute | AWS Lambda, container image, ARM64 | Cheapest cold-start path with Web Adapter |
| HTTP shim | AWS Lambda Web Adapter (extension) | Lets FastMCP's uvicorn run unmodified inside Lambda |
| Endpoint | Lambda Function URL, **Invoke mode = `RESPONSE_STREAM`** | MCP streaming requires it |
| Function URL auth | `NONE` with a shared-secret header (`X-MCP-Auth`) validated in-server | Works with any MCP HTTP client; no SigV4 friction. Document that switching to `AWS_IAM` later is a single template change. |
| Secrets | AWS Secrets Manager | `apollo/api-key` and `apollo/mcp-shared-secret` |
| IaC | AWS SAM (one template per MCP) | Simpler than CDK for two Lambdas; matches AWS-published examples |
| Region | `us-west-2` (default; allow override via env var) | Lowest latency to most users; Apollo is region-agnostic |
| Logs | CloudWatch + structured JSON via `structlog` | Observability without Powertools complications |

---

## 4. Repo structure (create exactly this)

```
apollo-mcp/
├── README.md
├── CLAUDE.md                       # this file (do not modify)
├── .gitignore                      # includes .env, .venv, .aws-sam, __pycache__
├── .env.example                    # APOLLO_API_KEY, MCP_SHARED_SECRET
├── pyproject.toml                  # workspace root
├── uv.lock
├── shared/
│   ├── __init__.py
│   ├── apollo_client.py            # async httpx client, retries, rate-limit-aware
│   ├── auth.py                     # X-MCP-Auth header validation middleware
│   ├── logging.py                  # structlog JSON config
│   └── models.py                   # shared Pydantic types (Contact, Company, etc.)
├── prospecting_mcp/
│   ├── __init__.py
│   ├── server.py                   # FastMCP server + tool definitions
│   ├── Dockerfile
│   ├── template.yaml               # SAM
│   └── tests/
│       ├── test_tools_unit.py      # mocked Apollo
│       └── test_tools_integration.py  # real Apollo, gated on env var
├── sending_mcp/
│   ├── __init__.py
│   ├── server.py
│   ├── Dockerfile
│   ├── template.yaml
│   └── tests/
│       ├── test_tools_unit.py
│       └── test_tools_integration.py
├── scripts/
│   ├── bootstrap.sh                # one-time: secrets, ECR repos
│   ├── deploy.sh                   # build + push + sam deploy, both stacks
│   ├── test_local.sh               # run both servers locally + smoke test
│   └── inspect.sh                  # opens MCP Inspector against the deployed URL
└── docs/
    ├── apollo-api-reference.md     # the prior research doc, checked in
    ├── shell-sequence-setup.md     # UI steps the user does once for sending-mcp
    └── runbook.md                  # rotate keys, redeploy, debug 4xx/5xx
```

---

## 5. Prerequisites — verify all before Phase 0

Run these checks. If any fails, stop and report to the user.

```bash
# Required tools
aws --version            # >= 2.32.0 (browser-based aws login supported)
docker --version         # docker daemon must be running: docker ps
uv --version             # >= 0.5
python3.12 --version

# Required AWS context
aws sts get-caller-identity                 # confirm signed in
aws configure get region                    # warn if not us-west-2
aws iam get-account-summary >/dev/null      # confirm permissions baseline
```

The user must have:
- An Apollo **master** API key (not a scoped one) — see `docs/apollo-api-reference.md`.
- Permission to create Lambda functions, ECR repos, Secrets Manager secrets, IAM roles in the target AWS account.

If the user hasn't pre-built the shell sequence in Apollo, **do not start Phase 2 (sending-mcp)** until they do. See `docs/shell-sequence-setup.md`.

---

## 6. Apollo contract — the bare minimum Claude Code needs to know

Full reference is in `docs/apollo-api-reference.md`. Critical points:

- Base URL: `https://api.apollo.io/api/v1`
- Auth header: `X-Api-Key: <master_key>`
- Most write endpoints (sequences, custom fields, bulk ops) **require master API key** or return 403.
- People search returns IDs only — emails come from a separate enrichment call (`POST /people/bulk_match` with `reveal_personal_emails=true`).
- "Lists" are labels. Pass `label_names[]` on contact create/update; the list materializes if it doesn't exist.
- **Sequences cannot be created via API.** They must exist in the Apollo UI. The sending-mcp depends on a pre-built shell sequence.
- Pagination cap: 100/page × 500 pages = 50,000 records max per query. Build narrowing in.
- Endpoints have per-tier rate limits visible at `POST /usage_stats/api_usage_stats`. Treat 429 as retryable with exponential backoff up to 3 retries.

---

## 7. Phase 0 — Bootstrap

### Steps

1. `git init` the repo, create the structure in §4 with empty files where needed.
2. Create `pyproject.toml`:
   ```toml
   [project]
   name = "apollo-mcp"
   version = "0.1.0"
   requires-python = ">=3.12"
   dependencies = [
     "fastmcp>=2.0",
     "httpx>=0.27",
     "pydantic>=2.7",
     "structlog>=24.1",
     "tenacity>=8.5",
   ]

   [dependency-groups]
   dev = [
     "pytest>=8.0",
     "pytest-asyncio>=0.23",
     "respx>=0.21",
     "mypy>=1.10",
     "ruff>=0.6",
   ]

   [tool.pytest.ini_options]
   asyncio_mode = "auto"
   ```
3. `uv sync` — confirm all deps install.
4. `.env.example`:
   ```
   APOLLO_API_KEY=
   MCP_SHARED_SECRET=
   APOLLO_BASE_URL=https://api.apollo.io/api/v1
   AWS_REGION=us-west-2
   ```
5. Implement `shared/apollo_client.py`:
   - `class ApolloClient` with async methods for every endpoint the two MCPs use (see §8.2 and §9.2 for the inventory).
   - Reads `APOLLO_API_KEY` from env (in Lambda, populated from Secrets Manager via env-var integration in the SAM template).
   - Sends `X-Api-Key` header.
   - 429 retry with `tenacity` (exp backoff, 3 attempts).
   - Returns parsed Pydantic models, not raw dicts.
6. Implement `shared/auth.py`:
   - FastMCP middleware (or a simple wrapper) that 401s any request missing `X-MCP-Auth: <MCP_SHARED_SECRET>`.
   - Constant-time comparison.
7. Implement `shared/logging.py` — structlog JSON renderer, log level from `LOG_LEVEL` env.
8. Run `scripts/bootstrap.sh` (next step) to create AWS resources.

### `scripts/bootstrap.sh` — what it does

```bash
#!/usr/bin/env bash
set -euo pipefail

REGION=${AWS_REGION:-us-west-2}

# 1. Secrets
aws secretsmanager create-secret \
  --name apollo/api-key \
  --description "Apollo.io master API key" \
  --secret-string "$APOLLO_API_KEY" \
  --region $REGION || echo "secret apollo/api-key already exists"

aws secretsmanager create-secret \
  --name apollo/mcp-shared-secret \
  --description "Shared secret for X-MCP-Auth header" \
  --secret-string "$(openssl rand -hex 32)" \
  --region $REGION || echo "secret apollo/mcp-shared-secret already exists"

# 2. ECR repos
aws ecr create-repository --repository-name prospecting-mcp --region $REGION || true
aws ecr create-repository --repository-name sending-mcp --region $REGION || true

echo "Done. Save the shared secret value:"
aws secretsmanager get-secret-value \
  --secret-id apollo/mcp-shared-secret \
  --region $REGION \
  --query SecretString --output text
```

### DoD for Phase 0

- [ ] `uv sync` succeeds
- [ ] `python -c "from shared.apollo_client import ApolloClient"` succeeds
- [ ] Two secrets exist: `aws secretsmanager list-secrets --region us-west-2` shows both
- [ ] Two ECR repos exist
- [ ] A canned unit test for `ApolloClient` (with `respx` mocking) passes: `uv run pytest shared/`

---

## 8. Phase 1 — Prospecting MCP

### 8.1 Pre-built shell sequence

Not required for prospecting-mcp. Skip.

### 8.2 Apollo endpoints used

| Tool intent | Apollo endpoint |
|---|---|
| Search people (no credit cost, no emails) | `POST /mixed_people/api_search` |
| Search companies | `POST /mixed_companies/search` |
| Enrich up to 10 people (gets emails) | `POST /people/bulk_match` |
| Enrich one company by domain | `GET /organizations/enrich` |
| Active job postings at a company (intent signal) | `GET /organizations/{id}/job_postings` |

### 8.3 MCP tool surface (final names + signatures — do not rename)

```python
# prospecting_mcp/server.py

from fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import Literal

mcp = FastMCP("apollo-prospecting", stateless_http=True)

# ---------- Models ----------

class PersonFilter(BaseModel):
    titles: list[str] | None = Field(None, description="Job titles, e.g. ['VP Sales']")
    seniorities: list[Literal[
        "owner","founder","c_suite","partner","vp","head",
        "director","manager","senior","entry","intern"
    ]] | None = None
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
    title: str | None
    company: str | None
    company_domain: str | None
    linkedin_url: str | None
    location: str | None

class EnrichedPerson(PersonSummary):
    email: str | None
    email_status: Literal["verified","unverified","likely_to_engage","unavailable"] | None
    phone: str | None

# ---------- Tools ----------

@mcp.tool
async def search_people(filters: PersonFilter) -> list[PersonSummary]:
    """Find prospects in Apollo's database matching the given filters.

    Does NOT return emails. Call enrich_people to reveal emails for the IDs you care about.
    Costs no Apollo credits. Capped at 50,000 records per filter combination.
    """
    ...

@mcp.tool
async def search_companies(filters: CompanyFilter) -> list[dict]:
    """Find companies matching firmographic + technographic filters.

    Returns company id, name, domain, industry, headcount range, revenue range, tech stack.
    Consumes Apollo credits.
    """
    ...

@mcp.tool
async def find_people_at_companies(
    company_filters: CompanyFilter,
    person_filters: PersonFilter,
    max_companies: int = 25,
    max_people_per_company: int = 5,
) -> list[PersonSummary]:
    """Two-step convenience: search companies, then find people at those companies
    matching person_filters. Returns flat list of people."""
    ...

@mcp.tool
async def enrich_people(
    person_ids: list[str],
    reveal_emails: bool = True,
    reveal_phones: bool = False,
) -> list[EnrichedPerson]:
    """Bulk-enrich up to 10 person IDs from search_people. Reveals emails (and optionally
    phones). This is where Apollo credits get spent."""
    if len(person_ids) > 10:
        raise ValueError("Apollo's bulk enrichment caps at 10 IDs per call. Chunk in the agent.")
    ...

@mcp.tool
async def enrich_company(domain: str) -> dict:
    """Enrich a single company by domain. Returns full firmographic profile."""
    ...

@mcp.tool
async def get_company_job_postings(organization_id: str) -> list[dict]:
    """Active job postings at a company. Useful as a buying-intent signal."""
    ...

if __name__ == "__main__":
    import os
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
    )
```

### 8.4 Implementation notes

- All tools are async. The Apollo client uses `httpx.AsyncClient`.
- Wire the `X-MCP-Auth` middleware on the FastMCP instance (FastMCP supports custom middleware via `add_middleware` or by mounting in a Starlette app — pick whichever is supported in the FastMCP version installed; check `uv pip show fastmcp` and adjust).
- The chunking constraint on `enrich_people` (≤10) is enforced at the tool boundary so the agent gets a clear error.
- Return Pydantic models. FastMCP will serialize them.

### 8.5 Local test

```bash
# Terminal 1
cd prospecting_mcp
uv run python server.py
# Should log: Uvicorn running on http://0.0.0.0:8080

# Terminal 2 — test with curl (initialize + list tools)
curl -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "X-MCP-Auth: $MCP_SHARED_SECRET" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}'

curl -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "X-MCP-Auth: $MCP_SHARED_SECRET" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# Terminal 2 — also test with MCP Inspector
npx @modelcontextprotocol/inspector
# In the UI: transport=streamable-http, URL=http://localhost:8080/mcp,
# header X-MCP-Auth: <secret>
```

### 8.6 DoD for Phase 1 (local)

- [ ] All 6 tools register and appear in `tools/list`
- [ ] `search_people` with `{titles: ["CISO"], person_locations: ["Denver, US"]}` returns ≥1 result against real Apollo (integration test, gated on `RUN_INTEGRATION=1`)
- [ ] `enrich_people` with the IDs from the prior call returns at least one verified email
- [ ] Auth middleware: missing or wrong `X-MCP-Auth` returns 401
- [ ] `uv run pytest prospecting_mcp/tests/test_tools_unit.py` is green (mocked)
- [ ] Type check passes: `uv run mypy prospecting_mcp shared`

---

## 9. Phase 2 — Sending MCP

### 9.1 Pre-built shell sequence (user task — verify before coding)

Before this phase, the user must complete `docs/shell-sequence-setup.md`:

1. In Apollo UI, create two **custom contact fields**:
   - `ai_email_subject` (text)
   - `ai_email_body` (long text)
2. Create a sequence named **`AI Bespoke Send`** (exact name) with a single **Automatic Email** step:
   - Subject: `{{ai_email_subject}}`
   - Body: `Hi {{#if first_name}}{{first_name}}{{#else}}there{{#endif}},`<br>`{{ai_email_body}}`<br>`— {{sender_first_name}}`
   - Wait time on step 1: 0 minutes
3. Activate the sequence.
4. Confirm at least one email mailbox is connected and not paused.

When the user confirms done, run an Apollo API check before proceeding:

```python
# Should find the sequence:
await apollo.search_sequences(q_name="AI Bespoke Send")
# Should find both custom fields:
await apollo.list_fields(source="custom")
# Should find at least one active mailbox:
await apollo.list_email_accounts()
```

If any check fails, stop and tell the user what's missing.

### 9.2 Apollo endpoints used

| Tool intent | Apollo endpoint |
|---|---|
| Find a contact by email | `POST /contacts/search` |
| Create / dedupe a contact | `POST /contacts` (with `run_dedupe=true`) |
| Update a contact's custom fields | `PATCH /contacts/{id}` |
| Find the shell sequence | `POST /emailer_campaigns/search` |
| Find the mailbox to send from | `GET /email_accounts` |
| Enroll the contact in the sequence | `POST /emailer_campaigns/{sequence_id}/add_contact_ids` |
| Pull mailbox + sequence stats | `GET /emailer_messages/search`, `GET /emailer_campaigns/check_email_stats` |

### 9.3 MCP tool surface

```python
# sending_mcp/server.py

from fastmcp import FastMCP
from pydantic import BaseModel, EmailStr, Field
from typing import Literal
from datetime import datetime

mcp = FastMCP("apollo-sending", stateless_http=True)

class SendResult(BaseModel):
    contact_id: str
    sequence_id: str
    mailbox_id: str
    status: Literal["enrolled_active", "enrolled_paused_until", "skipped_already_in_sequence"]
    scheduled_for: datetime | None
    apollo_warnings: list[str] = []

@mcp.tool
async def send_personalized_email(
    contact_email: EmailStr,
    subject: str = Field(..., max_length=200),
    body: str = Field(..., max_length=10_000, description="Plain text or basic HTML"),
    sequence_name: str = "AI Bespoke Send",
    mailbox_email: str | None = Field(
        None, description="Mailbox address to send from. Defaults to first active mailbox."
    ),
    schedule_at: datetime | None = Field(
        None, description="ISO 8601 UTC. If set, contact is enrolled paused and auto-unpaused at this time."
    ),
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
    ...

@mcp.tool
async def get_send_status(contact_email: EmailStr, sequence_name: str = "AI Bespoke Send") -> dict:
    """Check whether the contact has been sent the email yet, opened it, replied, etc."""
    ...

@mcp.tool
async def list_active_mailboxes() -> list[dict]:
    """List the mailboxes the agent can pick from for the mailbox_email parameter."""
    ...

if __name__ == "__main__":
    import os
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
    )
```

### 9.4 Implementation flow inside `send_personalized_email`

```
1. Resolve sequence_id: search_sequences(q_name=sequence_name) → first exact-name match
   - If not found: raise ToolError("Sequence not found. Build it in Apollo UI per docs/shell-sequence-setup.md")
2. Resolve mailbox_id:
   - If mailbox_email given: list_email_accounts() → match by email
   - Else: pick first active mailbox
3. Resolve contact_id:
   - search_contacts(q_keywords=contact_email) → match
   - If not found and create_if_missing: create_contact(email=contact_email, run_dedupe=true)
   - If not found and not create_if_missing: raise ToolError
4. Update contact custom fields:
   - update_contact(contact_id, typed_custom_fields={"ai_email_subject": subject, "ai_email_body": body})
5. Enroll:
   - add_to_sequence(
       sequence_id, contact_ids=[contact_id], emailer_campaign_id=sequence_id,
       send_email_from_email_account_id=mailbox_id,
       status="paused" if schedule_at else "active",
       auto_unpause_at=schedule_at.isoformat() if schedule_at else None,
       sequence_active_in_other_campaigns=False,  # don't double-touch
       sequence_unverified_email=False,           # safety default
     )
6. Map Apollo response → SendResult, including any warnings about already-enrolled, etc.
```

### 9.5 Local test

```bash
# Pick a real prospect you control (or a test mailbox you own).
# Set TEST_PROSPECT_EMAIL=you+test@yourdomain.com in .env

uv run python sending_mcp/server.py &

# Send to yourself:
curl -X POST http://localhost:8080/mcp \
  -H "X-MCP-Auth: $MCP_SHARED_SECRET" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{
    "jsonrpc":"2.0","id":1,
    "method":"tools/call",
    "params":{
      "name":"send_personalized_email",
      "arguments":{
        "contact_email":"'$TEST_PROSPECT_EMAIL'",
        "subject":"Quick test from the MCP",
        "body":"This is the body."
      }
    }
  }'

# Watch the inbox. Confirm the email arrives within the schedule window.
```

### 9.6 DoD for Phase 2 (local)

- [ ] All 3 tools register
- [ ] `list_active_mailboxes` returns ≥1 mailbox
- [ ] Sending to a real test address results in a delivered email matching the subject and body sent
- [ ] Re-sending to the same address returns `status='skipped_already_in_sequence'` (no duplicate)
- [ ] `get_send_status` returns sent/opened/replied state correctly after the email lands
- [ ] Auth middleware enforced (401 on missing/bad header)

---

## 10. Phase 3 — Containerize

### 10.1 Dockerfile (use this for **both** MCPs; only the COPY line differs)

```dockerfile
# Lambda Web Adapter as an extension
FROM --platform=linux/arm64 public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 AS adapter

FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /var/task

# Install the adapter into Lambda's extensions dir
COPY --from=adapter /lambda-adapter /opt/extensions/lambda-adapter

# Hardening + perf
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    AWS_LAMBDA_EXEC_WRAPPER=/opt/extensions/lambda-adapter \
    AWS_LWA_INVOKE_MODE=response_stream \
    AWS_LWA_READINESS_CHECK_PATH=/mcp

# Install uv, then deps
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# App code — change this line per MCP
COPY shared/ ./shared/
COPY prospecting_mcp/ ./prospecting_mcp/

CMD ["uv", "run", "python", "-m", "prospecting_mcp.server"]
```

For `sending_mcp/Dockerfile`, swap the `COPY` and `CMD` lines accordingly.

### 10.2 Local container test

```bash
docker build -t prospecting-mcp:local -f prospecting_mcp/Dockerfile .
docker run --rm -p 8080:8080 \
  -e APOLLO_API_KEY=$APOLLO_API_KEY \
  -e MCP_SHARED_SECRET=$MCP_SHARED_SECRET \
  prospecting-mcp:local

# In another shell, hit it the same way as in §8.5
```

### 10.3 DoD for Phase 3

- [ ] Both images build for `linux/arm64`
- [ ] Both run locally and pass the curl smoke test from §8.5
- [ ] Image size <500 MB (Lambda allows up to 10 GB but smaller = faster cold start)

---

## 11. Phase 4 — Deploy

### 11.1 SAM template skeleton (`prospecting_mcp/template.yaml`)

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: Apollo Prospecting MCP

Parameters:
  ApolloApiKeySecretArn:
    Type: String
  McpSharedSecretArn:
    Type: String
  ImageUri:
    Type: String

Resources:
  ProspectingMcpFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: apollo-prospecting-mcp
      PackageType: Image
      ImageUri: !Ref ImageUri
      Architectures: [arm64]
      MemorySize: 1024
      Timeout: 60                        # MCP tool calls can take a moment for Apollo
      Environment:
        Variables:
          APOLLO_BASE_URL: https://api.apollo.io/api/v1
          AWS_LWA_INVOKE_MODE: response_stream
          LOG_LEVEL: INFO
          # The next two come from Secrets Manager via the SecretsManager extension
          APOLLO_API_KEY: !Sub '{{resolve:secretsmanager:${ApolloApiKeySecretArn}}}'
          MCP_SHARED_SECRET: !Sub '{{resolve:secretsmanager:${McpSharedSecretArn}}}'
      Policies:
        - Version: '2012-10-17'
          Statement:
            - Effect: Allow
              Action: secretsmanager:GetSecretValue
              Resource:
                - !Ref ApolloApiKeySecretArn
                - !Ref McpSharedSecretArn
      FunctionUrlConfig:
        AuthType: NONE                    # auth handled in-app via X-MCP-Auth
        InvokeMode: RESPONSE_STREAM
        Cors:
          AllowOrigins: ['*']
          AllowHeaders: ['*']
          AllowMethods: ['*']

Outputs:
  FunctionUrl:
    Value: !GetAtt ProspectingMcpFunctionUrl.FunctionUrl
  FunctionArn:
    Value: !GetAtt ProspectingMcpFunction.Arn
```

Same shape for `sending_mcp/template.yaml`, just rename the function and image URI.

### 11.2 `scripts/deploy.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

REGION=${AWS_REGION:-us-west-2}
ACCT=$(aws sts get-caller-identity --query Account --output text)

APOLLO_SECRET_ARN=$(aws secretsmanager describe-secret --secret-id apollo/api-key --region $REGION --query ARN --output text)
MCP_SECRET_ARN=$(aws secretsmanager describe-secret --secret-id apollo/mcp-shared-secret --region $REGION --query ARN --output text)

aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCT.dkr.ecr.$REGION.amazonaws.com

for app in prospecting sending; do
  IMG=$ACCT.dkr.ecr.$REGION.amazonaws.com/${app}-mcp:latest
  docker build --platform linux/arm64 -t $IMG -f ${app}_mcp/Dockerfile .
  docker push $IMG

  sam deploy \
    --template-file ${app}_mcp/template.yaml \
    --stack-name apollo-${app}-mcp \
    --region $REGION \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
      ApolloApiKeySecretArn=$APOLLO_SECRET_ARN \
      McpSharedSecretArn=$MCP_SECRET_ARN \
      ImageUri=$IMG \
    --no-confirm-changeset

  URL=$(aws cloudformation describe-stacks \
    --stack-name apollo-${app}-mcp \
    --region $REGION \
    --query "Stacks[0].Outputs[?OutputKey=='FunctionUrl'].OutputValue" \
    --output text)
  echo "${app}-mcp URL: $URL"
done
```

### 11.3 Test deployed URLs

```bash
PROSP_URL=$(aws cloudformation describe-stacks --stack-name apollo-prospecting-mcp --region us-west-2 --query "Stacks[0].Outputs[?OutputKey=='FunctionUrl'].OutputValue" --output text)

curl -X POST "${PROSP_URL}mcp" \
  -H "X-MCP-Auth: $MCP_SHARED_SECRET" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### 11.4 DoD for Phase 4

- [ ] Both stacks deployed: `aws cloudformation list-stacks --region us-west-2 | grep apollo`
- [ ] Both Function URLs return 200 + tool list when called with the correct `X-MCP-Auth`
- [ ] Both URLs return 401 when called without the header
- [ ] CloudWatch shows clean startup logs (no Python tracebacks) for both functions
- [ ] Cold-start latency on first invoke logged; warm-invoke latency under 2s for `tools/list`

---

## 12. Phase 5 — Connect to a client

For Claude Code itself or a Claude Desktop config:

```jsonc
{
  "mcpServers": {
    "apollo-prospecting": {
      "type": "http",
      "url": "https://<id>.lambda-url.us-west-2.on.aws/mcp",
      "headers": {
        "X-MCP-Auth": "<the shared secret value from Secrets Manager>"
      }
    },
    "apollo-sending": {
      "type": "http",
      "url": "https://<id>.lambda-url.us-west-2.on.aws/mcp",
      "headers": {
        "X-MCP-Auth": "<same shared secret>"
      }
    }
  }
}
```

For an in-house agent, use FastMCP's client:

```python
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

prospecting = Client(StreamableHttpTransport(
    "https://<id>.lambda-url.us-west-2.on.aws/mcp",
    headers={"X-MCP-Auth": SECRET},
))
```

### DoD for Phase 5

- [ ] Inspector or Claude Desktop shows both MCPs connected
- [ ] Inspector can call `search_people` and see results
- [ ] Inspector can call `send_personalized_email` to a test address and the email arrives

---

## 13. Out of scope (do not implement; explain to user if asked)

- **Creating sequences via API** — Apollo has no such endpoint. Document the manual UI step instead.
- **Sending one-off emails outside of sequences** — same constraint. The shell-sequence pattern is the only path.
- **LinkedIn outreach** — Apollo removed first-party LinkedIn automation in January 2026.
- **OAuth on the Function URL** — defer until v2. Shared-secret header is sufficient for v1.
- **Multi-tenant support** — single Apollo workspace per deployment. Multi-tenant requires per-tenant secrets and routing.

---

## 14. Open questions to confirm with the user before starting

Ask in this order, one at a time:

1. AWS region — `us-west-2` ok or different?
2. Will the sending mailbox be Michael's personal mailbox or a shared team mailbox?
3. Should there be a separate "test" mode that no-ops the actual Apollo enrollment (returns mock SendResult) for safer agent dev? Default: no, but add a feature flag if requested.
4. Rate-limit handling: hard fail on 429 after 3 retries, or queue + return a "queued" response? Default: hard fail (fail fast for agents).

---

## 15. When done

Update `README.md` with:
- One-paragraph description of each MCP
- The two Function URLs
- Where the shared secret lives (`aws secretsmanager get-secret-value --secret-id apollo/mcp-shared-secret`)
- Link to `docs/runbook.md` for redeploys, key rotation, common 4xx/5xx debugging
- Link back to `docs/apollo-api-reference.md`

Open a PR titled `feat: apollo prospecting + sending MCPs on Lambda`.
