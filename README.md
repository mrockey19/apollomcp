# Apollo MCP Stack

Two production-grade MCP servers wrapping Apollo.io for an outreach agent stack, deployed as AWS Lambda container images.

## Servers

### prospecting-mcp
Searches Apollo for people and companies matching filters, returns enriched contact data including emails. Tools: `search_people`, `search_companies`, `find_people_at_companies`, `enrich_people`, `enrich_company`, `get_company_job_postings`.

### sending-mcp
Sends fully personalized, per-prospect emails by enrolling contacts into a pre-built Apollo sequence with custom field-driven content. Tools: `send_personalized_email`, `get_send_status`, `list_active_mailboxes`.

## Setup

1. Install prerequisites: `uv`, Python 3.12, AWS CLI, Docker, SAM CLI
2. Copy `.env.example` to `.env` and fill in your Apollo API key
3. `uv sync`
4. Run `./scripts/bootstrap.sh` to create AWS Secrets Manager secrets and ECR repos
5. For the sending-mcp, complete the [shell sequence setup](docs/shell-sequence-setup.md) in Apollo UI
6. Deploy: `./scripts/deploy.sh`

## Function URLs

After deployment:
```bash
for stack in apollo-prospecting-mcp apollo-sending-mcp; do
  aws cloudformation describe-stacks \
    --stack-name $stack --region us-east-1 \
    --query "Stacks[0].Outputs[?OutputKey=='FunctionUrl'].OutputValue" \
    --output text
done
```

## Shared Secret

```bash
aws secretsmanager get-secret-value \
  --secret-id apollo/mcp-shared-secret \
  --region us-east-1 \
  --query SecretString --output text
```

## Documentation

- [Apollo API Reference](docs/apollo-api-reference.md)
- [Shell Sequence Setup](docs/shell-sequence-setup.md) (required for sending-mcp)
- [Operations Runbook](docs/runbook.md) — redeploy, rotate keys, debug errors
