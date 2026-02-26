#!/bin/bash
# E2E検証用インフラストラクチャセットアップスクリプト
# Usage: ./setup-infrastructure.sh <region> <project-prefix>

set -e

REGION=${1:-us-east-1}
PREFIX=${2:-agentcore-auth-test}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "[INFO] Setting up AgentCore Auth E2E Verification Infrastructure"
echo "[INFO] Region: $REGION"
echo "[INFO] Prefix: $PREFIX"
echo "[INFO] Account: $ACCOUNT_ID"

# 1. Cognito User Pool の作成
echo "[STEP 1/7] Creating Cognito User Pool..."

# 既存のUser Poolを検索
EXISTING_POOL_ID=$(aws cognito-idp list-user-pools --max-results 10 --region $REGION \
  --query "UserPools[?Name=='${PREFIX}-user-pool'].Id" --output text)

if [ -n "$EXISTING_POOL_ID" ]; then
  echo "[INFO] User Pool already exists: $EXISTING_POOL_ID"
  USER_POOL_ID=$EXISTING_POOL_ID
else
  # カスタム属性のスキーマを定義
  USER_POOL_ID=$(aws cognito-idp create-user-pool \
    --pool-name "${PREFIX}-user-pool" \
    --region $REGION \
    --policies "PasswordPolicy={MinimumLength=8,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=false}" \
    --auto-verified-attributes email \
    --schema \
      Name=email,Required=true,Mutable=false,AttributeDataType=String \
      Name=custom:tenant_id,AttributeDataType=String,Mutable=true \
      Name=custom:agent_id,AttributeDataType=String,Mutable=true \
    --query 'UserPool.Id' --output text)
  echo "[INFO] User Pool created: $USER_POOL_ID"
fi

# Cognito User Pool のJWKS URLを取得
JWKS_URL="https://cognito-idp.${REGION}.amazonaws.com/${USER_POOL_ID}/.well-known/jwks.json"
echo "[INFO] JWKS URL: $JWKS_URL"

# App Client の作成
echo "[STEP 2/7] Creating Cognito App Client..."

# 既存のApp Clientを検索
EXISTING_CLIENT_ID=$(aws cognito-idp list-user-pool-clients --user-pool-id $USER_POOL_ID --region $REGION \
  --query "UserPoolClients[?ClientName=='${PREFIX}-client'].ClientId" --output text | head -1)

if [ -n "$EXISTING_CLIENT_ID" ]; then
  echo "[INFO] App Client already exists: $EXISTING_CLIENT_ID"
  CLIENT_ID=$EXISTING_CLIENT_ID
else
  CLIENT_ID=$(aws cognito-idp create-user-pool-client \
    --user-pool-id $USER_POOL_ID \
    --client-name "${PREFIX}-client" \
    --region $REGION \
    --generate-secret \
    --explicit-auth-flows ADMIN_NO_SRP_AUTH \
    --query 'UserPoolClient.ClientId' --output text)
  echo "[INFO] App Client created: $CLIENT_ID"
fi

if [ -z "$CLIENT_ID" ]; then
  echo "[ERROR] Failed to create or find App Client"
  exit 1
fi

echo "[INFO] App Client ID: $CLIENT_ID"

# 2. DynamoDB テーブルの作成
echo "[STEP 3/7] Creating DynamoDB Tables..."

# Tenants Table
aws dynamodb create-table \
  --table-name "${PREFIX}-tenants" \
  --region $REGION \
  --attribute-definitions \
    AttributeName=tenant_id,AttributeType=S \
  --key-schema \
    AttributeName=tenant_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --tags Key=Project,Value=AgentCoreAuthE2E 2>/dev/null || echo "[INFO] Tenants table already exists"

# Sharing Table
aws dynamodb create-table \
  --table-name "${PREFIX}-sharing" \
  --region $REGION \
  --attribute-definitions \
    AttributeName=resource_id,AttributeType=S \
    AttributeName=consumer_tenant_id,AttributeType=S \
  --key-schema \
    AttributeName=resource_id,KeyType=HASH \
    AttributeName=consumer_tenant_id,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --tags Key=Project,Value=AgentCoreAuthE2E 2>/dev/null || echo "[INFO] Sharing table already exists"

# AuthPolicy Table
aws dynamodb create-table \
  --table-name "${PREFIX}-auth-policy" \
  --region $REGION \
  --attribute-definitions \
    AttributeName=email,AttributeType=S \
  --key-schema \
    AttributeName=email,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --tags Key=Project,Value=AgentCoreAuthE2E 2>/dev/null || echo "[INFO] AuthPolicy table already exists"

echo "[INFO] Waiting for tables to be active..."
aws dynamodb wait table-exists --table-name "${PREFIX}-tenants" --region $REGION
aws dynamodb wait table-exists --table-name "${PREFIX}-sharing" --region $REGION
aws dynamodb wait table-exists --table-name "${PREFIX}-auth-policy" --region $REGION

# 3. テストデータの投入
echo "[STEP 4/7] Inserting test data..."

# Tenant A
aws dynamodb put-item \
  --table-name "${PREFIX}-tenants" \
  --region $REGION \
  --item '{
    "tenant_id": {"S": "tenant-a"},
    "tenant_name": {"S": "Test Tenant A"},
    "status": {"S": "active"}
  }'

# Tenant B
aws dynamodb put-item \
  --table-name "${PREFIX}-tenants" \
  --region $REGION \
  --item '{
    "tenant_id": {"S": "tenant-b"},
    "tenant_name": {"S": "Test Tenant B"},
    "status": {"S": "active"}
  }'

# Test Users
aws dynamodb put-item \
  --table-name "${PREFIX}-auth-policy" \
  --region $REGION \
  --item '{
    "email": {"S": "admin@tenant-a.example.com"},
    "tenant_id": {"S": "tenant-a"},
    "role": {"S": "admin"},
    "groups": {"SS": ["admin", "users"]},
    "agent_id": {"S": "agent-001"}
  }'

aws dynamodb put-item \
  --table-name "${PREFIX}-auth-policy" \
  --region $REGION \
  --item '{
    "email": {"S": "user@tenant-a.example.com"},
    "tenant_id": {"S": "tenant-a"},
    "role": {"S": "user"},
    "groups": {"SS": ["users"]},
    "agent_id": {"S": "agent-002"}
  }'

aws dynamodb put-item \
  --table-name "${PREFIX}-auth-policy" \
  --region $REGION \
  --item '{
    "email": {"S": "user@tenant-b.example.com"},
    "tenant_id": {"S": "tenant-b"},
    "role": {"S": "user"},
    "groups": {"SS": ["users"]},
    "agent_id": {"S": "agent-003"}
  }'

# Private Sharing: resource-001 を tenant-a から tenant-b へ共有
aws dynamodb put-item \
  --table-name "${PREFIX}-sharing" \
  --region $REGION \
  --item '{
    "resource_id": {"S": "resource-001"},
    "consumer_tenant_id": {"S": "tenant-b"},
    "owner_tenant_id": {"S": "tenant-a"},
    "sharing_mode": {"S": "private"}
  }'

# 4. IAM Role for Lambda
echo "[STEP 5/7] Creating IAM Role for Lambda..."
ROLE_NAME="${PREFIX}-lambda-role"

# Trust Policy
cat > /tmp/trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
  --role-name $ROLE_NAME \
  --assume-role-policy-document file:///tmp/trust-policy.json 2>/dev/null || echo "[INFO] IAM Role already exists"

# Attach policies
aws iam attach-role-policy \
  --role-name $ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null || true

aws iam attach-role-policy \
  --role-name $ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBReadOnlyAccess 2>/dev/null || true

LAMBDA_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "[INFO] Lambda Role ARN: $LAMBDA_ROLE_ARN"

# 5. Lambda Layer for PyJWT
echo "[STEP 6/7] Creating Lambda Layer for PyJWT..."
cd /tmp
mkdir -p python
pip install PyJWT cryptography -t python/ --quiet
zip -r pyjwt-layer.zip python/ > /dev/null
LAYER_ARN=$(aws lambda publish-layer-version \
  --layer-name "${PREFIX}-pyjwt-layer" \
  --region $REGION \
  --zip-file fileb://pyjwt-layer.zip \
  --compatible-runtimes python3.11 python3.12 \
  --query 'LayerVersionArn' --output text 2>/dev/null)
rm -rf python pyjwt-layer.zip

echo "[INFO] Layer ARN: $LAYER_ARN"

# 6. 環境変数ファイルを出力
echo "[STEP 7/7] Generating environment configuration..."
cat > /home/coder/data-science/agent-auth-book/e2e-verification/.env <<EOF
# AWS Configuration
AWS_REGION=$REGION
AWS_ACCOUNT_ID=$ACCOUNT_ID

# Cognito Configuration
USER_POOL_ID=$USER_POOL_ID
CLIENT_ID=$CLIENT_ID
JWKS_URL=$JWKS_URL

# DynamoDB Tables
TENANT_TABLE=${PREFIX}-tenants
SHARING_TABLE=${PREFIX}-sharing
AUTH_POLICY_TABLE=${PREFIX}-auth-policy

# Lambda Configuration
LAMBDA_ROLE_ARN=$LAMBDA_ROLE_ARN
PYJWT_LAYER_ARN=$LAYER_ARN

# Project Configuration
PROJECT_PREFIX=$PREFIX
EOF

echo ""
echo "[SUCCESS] Infrastructure setup completed!"
echo ""
echo "Configuration saved to: /home/coder/data-science/agent-auth-book/e2e-verification/.env"
echo ""
echo "Next steps:"
echo "  1. Deploy Lambda functions: ./deploy-lambda-functions.sh"
echo "  2. Run E2E tests: python e2e-test.py"
echo ""
