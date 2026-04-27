#!/usr/bin/env bash
set -euo pipefail

REGION=${AWS_REGION:-us-east-1}

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
