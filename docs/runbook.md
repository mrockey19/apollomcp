# Operations Runbook

## Redeploy

```bash
# From repo root
./scripts/deploy.sh
```

This builds both container images, pushes to ECR, and runs `sam deploy` for both stacks.

## Rotate Apollo API Key

1. Generate a new master key in Apollo UI
2. Update the secret:
   ```bash
   aws secretsmanager update-secret \
     --secret-id apollo/api-key \
     --secret-string "NEW_KEY_HERE" \
     --region us-east-1
   ```
3. Redeploy both Lambdas (they read the secret at cold start):
   ```bash
   ./scripts/deploy.sh
   ```

## Rotate MCP Shared Secret

1. Generate a new secret:
   ```bash
   NEW_SECRET=$(openssl rand -hex 32)
   aws secretsmanager update-secret \
     --secret-id apollo/mcp-shared-secret \
     --secret-string "$NEW_SECRET" \
     --region us-east-1
   ```
2. Redeploy both Lambdas:
   ```bash
   ./scripts/deploy.sh
   ```
3. Update all MCP clients with the new `X-MCP-Auth` value.

## Common Errors

### 401 Unauthorized
- Missing or incorrect `X-MCP-Auth` header
- Check: `aws secretsmanager get-secret-value --secret-id apollo/mcp-shared-secret --region us-east-1 --query SecretString --output text`

### 403 Forbidden from Apollo
- Using a scoped API key instead of a master key
- Endpoint requires master key permissions

### 429 Rate Limited
- Apollo rate limits exceeded
- The client retries 3 times with exponential backoff then fails
- Check usage: `POST /usage_stats/api_usage_stats`

### 500 Internal Server Error
- Check CloudWatch logs:
  ```bash
  aws logs tail /aws/lambda/apollo-prospecting-mcp --region us-east-1 --follow
  aws logs tail /aws/lambda/apollo-sending-mcp --region us-east-1 --follow
  ```

## View Function URLs

```bash
for stack in apollo-prospecting-mcp apollo-sending-mcp; do
  echo "$stack:"
  aws cloudformation describe-stacks \
    --stack-name $stack \
    --region us-east-1 \
    --query "Stacks[0].Outputs[?OutputKey=='FunctionUrl'].OutputValue" \
    --output text
done
```
