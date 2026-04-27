#!/usr/bin/env bash
set -euo pipefail

REGION=${AWS_REGION:-us-east-1}
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
