#!/usr/bin/env bash
set -euo pipefail

REGION=${AWS_REGION:-us-east-1}

if [ "${1:-}" = "sending" ]; then
  STACK="apollo-sending-mcp"
else
  STACK="apollo-prospecting-mcp"
fi

URL=$(aws cloudformation describe-stacks \
  --stack-name $STACK \
  --region $REGION \
  --query "Stacks[0].Outputs[?OutputKey=='FunctionUrl'].OutputValue" \
  --output text)

echo "Opening MCP Inspector for $STACK at ${URL}mcp"
echo "Add header X-MCP-Auth with the shared secret from:"
echo "  aws secretsmanager get-secret-value --secret-id apollo/mcp-shared-secret --region $REGION --query SecretString --output text"
echo ""

npx @modelcontextprotocol/inspector
