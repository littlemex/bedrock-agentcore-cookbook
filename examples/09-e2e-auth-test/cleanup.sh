#!/bin/bash
# E2E検証環境のクリーンアップスクリプト
# Usage: ./cleanup.sh

set -e

# Load environment variables
if [ ! -f .env ]; then
  echo "[ERROR] .env file not found. Nothing to cleanup."
  exit 1
fi

source .env

echo "[WARNING] This will delete all E2E verification resources."
echo "Region: $AWS_REGION"
echo "Project: $PROJECT_PREFIX"
echo ""
read -p "Are you sure you want to continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "[CANCELLED] Cleanup cancelled."
    exit 0
fi

echo ""
echo "[INFO] Starting cleanup..."

# 1. Lambda関数の削除
echo "[STEP 1/5] Deleting Lambda functions..."
FUNCTIONS=(
    "${PROJECT_PREFIX}-authorizer-basic"
    "${PROJECT_PREFIX}-authorizer-saas"
    "${PROJECT_PREFIX}-request-interceptor-basic"
    "${PROJECT_PREFIX}-request-interceptor-sharing"
    "${PROJECT_PREFIX}-response-interceptor-basic"
    "${PROJECT_PREFIX}-pre-token-gen-v2"
)

for func in "${FUNCTIONS[@]}"; do
    aws lambda delete-function \
        --function-name $func \
        --region $AWS_REGION 2>/dev/null && echo "  Deleted: $func" || echo "  Not found: $func"
done

# 2. Lambda Layerの削除（最新バージョンのみ）
echo "[STEP 2/5] Deleting Lambda Layer..."
LAYER_VERSIONS=$(aws lambda list-layer-versions \
    --layer-name "${PROJECT_PREFIX}-pyjwt-layer" \
    --region $AWS_REGION \
    --query 'LayerVersions[].Version' \
    --output text 2>/dev/null || echo "")

for version in $LAYER_VERSIONS; do
    aws lambda delete-layer-version \
        --layer-name "${PROJECT_PREFIX}-pyjwt-layer" \
        --version-number $version \
        --region $AWS_REGION 2>/dev/null && echo "  Deleted layer version: $version"
done

# 3. DynamoDBテーブルの削除
echo "[STEP 3/5] Deleting DynamoDB tables..."
TABLES=(
    "${PROJECT_PREFIX}-tenants"
    "${PROJECT_PREFIX}-sharing"
    "${PROJECT_PREFIX}-auth-policy"
)

for table in "${TABLES[@]}"; do
    aws dynamodb delete-table \
        --table-name $table \
        --region $AWS_REGION 2>/dev/null && echo "  Deleted: $table" || echo "  Not found: $table"
done

# 4. Cognito User Poolの削除
echo "[STEP 4/5] Deleting Cognito User Pool..."
aws cognito-idp delete-user-pool \
    --user-pool-id $USER_POOL_ID \
    --region $AWS_REGION 2>/dev/null && echo "  Deleted: $USER_POOL_ID" || echo "  Not found: $USER_POOL_ID"

# 5. IAM Roleの削除
echo "[STEP 5/5] Deleting IAM Role..."
ROLE_NAME="${PROJECT_PREFIX}-lambda-role"

# ポリシーのデタッチ
aws iam detach-role-policy \
    --role-name $ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null || true

aws iam detach-role-policy \
    --role-name $ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBReadOnlyAccess 2>/dev/null || true

# ロールの削除
aws iam delete-role \
    --role-name $ROLE_NAME 2>/dev/null && echo "  Deleted: $ROLE_NAME" || echo "  Not found: $ROLE_NAME"

echo ""
echo "[SUCCESS] Cleanup completed!"
echo ""
echo "Deleted resources:"
echo "  - Lambda functions: ${#FUNCTIONS[@]}"
echo "  - DynamoDB tables: ${#TABLES[@]}"
echo "  - Cognito User Pool: 1"
echo "  - IAM Role: 1"
echo ""
echo "To remove configuration: rm .env"
echo ""
