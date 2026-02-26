#!/bin/bash
# Lambda関数デプロイスクリプト
# Usage: ./deploy-lambda-functions.sh

set -e

# Load environment variables
if [ ! -f .env ]; then
  echo "[ERROR] .env file not found. Run setup-infrastructure.sh first."
  exit 1
fi

source .env

echo "[INFO] Deploying Lambda functions..."
echo "[INFO] Region: $AWS_REGION"
echo "[INFO] Project: $PROJECT_PREFIX"

COOKBOOK_DIR="/home/coder/data-science/agent-auth-book/cookbook"

# 1. Lambda Authorizer (Basic)
echo "[STEP 1/6] Deploying Lambda Authorizer (Basic)..."
cd $COOKBOOK_DIR/lambda-authorizer
zip -q authorizer_basic.zip authorizer_basic.py

# 既存の関数を確認
if aws lambda get-function --function-name "${PROJECT_PREFIX}-authorizer-basic" --region $AWS_REGION > /dev/null 2>&1; then
  echo "[INFO] Updating existing function..."
  aws lambda update-function-code \
    --function-name "${PROJECT_PREFIX}-authorizer-basic" \
    --region $AWS_REGION \
    --zip-file fileb://authorizer_basic.zip > /dev/null

  aws lambda wait function-updated --function-name "${PROJECT_PREFIX}-authorizer-basic" --region $AWS_REGION

  aws lambda update-function-configuration \
    --function-name "${PROJECT_PREFIX}-authorizer-basic" \
    --region $AWS_REGION \
    --environment "Variables={JWKS_URL=${JWKS_URL},CLIENT_ID=${CLIENT_ID}}" > /dev/null
else
  echo "[INFO] Creating new function..."
  aws lambda create-function \
    --function-name "${PROJECT_PREFIX}-authorizer-basic" \
    --region $AWS_REGION \
    --runtime python3.12 \
    --role $LAMBDA_ROLE_ARN \
    --handler authorizer_basic.lambda_handler \
    --zip-file fileb://authorizer_basic.zip \
    --timeout 30 \
    --layers $PYJWT_LAYER_ARN \
    --environment "Variables={JWKS_URL=${JWKS_URL},CLIENT_ID=${CLIENT_ID}}" > /dev/null
fi

echo "[INFO] Authorizer Basic deployed"

# 2. Lambda Authorizer (SaaS)
echo "[STEP 2/6] Deploying Lambda Authorizer (SaaS)..."
zip -q authorizer_saas.zip authorizer_saas.py

if aws lambda get-function --function-name "${PROJECT_PREFIX}-authorizer-saas" --region $AWS_REGION > /dev/null 2>&1; then
  aws lambda update-function-code \
    --function-name "${PROJECT_PREFIX}-authorizer-saas" \
    --region $AWS_REGION \
    --zip-file fileb://authorizer_saas.zip > /dev/null
  aws lambda wait function-updated --function-name "${PROJECT_PREFIX}-authorizer-saas" --region $AWS_REGION
  aws lambda update-function-configuration \
    --function-name "${PROJECT_PREFIX}-authorizer-saas" \
    --region $AWS_REGION \
    --environment "Variables={JWKS_URL=${JWKS_URL},CLIENT_ID=${CLIENT_ID},TENANT_TABLE=${TENANT_TABLE}}" > /dev/null
else
  aws lambda create-function \
    --function-name "${PROJECT_PREFIX}-authorizer-saas" \
    --region $AWS_REGION \
    --runtime python3.12 \
    --role $LAMBDA_ROLE_ARN \
    --handler authorizer_saas.lambda_handler \
    --zip-file fileb://authorizer_saas.zip \
    --timeout 30 \
    --layers $PYJWT_LAYER_ARN \
    --environment "Variables={JWKS_URL=${JWKS_URL},CLIENT_ID=${CLIENT_ID},TENANT_TABLE=${TENANT_TABLE}}" > /dev/null
fi

echo "[INFO] Authorizer SaaS deployed"

# 3. Request Interceptor (Basic)
echo "[STEP 3/6] Deploying Request Interceptor (Basic)..."
cd $COOKBOOK_DIR/request-interceptor
zip -q interceptor_basic.zip interceptor_basic.py

aws lambda create-function \
  --function-name "${PROJECT_PREFIX}-request-interceptor-basic" \
  --region $AWS_REGION \
  --runtime python3.12 \
  --role $LAMBDA_ROLE_ARN \
  --handler interceptor_basic.lambda_handler \
  --zip-file fileb://interceptor_basic.zip \
  --timeout 30 \
  --layers $PYJWT_LAYER_ARN \
  --environment "Variables={JWKS_URL=${JWKS_URL},CLIENT_ID=${CLIENT_ID}}" 2>/dev/null || \
aws lambda update-function-code \
  --function-name "${PROJECT_PREFIX}-request-interceptor-basic" \
  --region $AWS_REGION \
  --zip-file fileb://interceptor_basic.zip > /dev/null && \
aws lambda update-function-configuration \
  --function-name "${PROJECT_PREFIX}-request-interceptor-basic" \
  --region $AWS_REGION \
  --environment "Variables={JWKS_URL=${JWKS_URL},CLIENT_ID=${CLIENT_ID}}" > /dev/null

echo "[INFO] Request Interceptor Basic deployed"

# 4. Request Interceptor (Private Sharing)
echo "[STEP 4/6] Deploying Request Interceptor (Private Sharing)..."
zip -q interceptor_private_sharing.zip interceptor_private_sharing.py

aws lambda create-function \
  --function-name "${PROJECT_PREFIX}-request-interceptor-sharing" \
  --region $AWS_REGION \
  --runtime python3.12 \
  --role $LAMBDA_ROLE_ARN \
  --handler interceptor_private_sharing.lambda_handler \
  --zip-file fileb://interceptor_private_sharing.zip \
  --timeout 30 \
  --environment "Variables={SHARING_TABLE=${SHARING_TABLE}}" 2>/dev/null || \
aws lambda update-function-code \
  --function-name "${PROJECT_PREFIX}-request-interceptor-sharing" \
  --region $AWS_REGION \
  --zip-file fileb://interceptor_private_sharing.zip > /dev/null && \
aws lambda update-function-configuration \
  --function-name "${PROJECT_PREFIX}-request-interceptor-sharing" \
  --region $AWS_REGION \
  --environment "Variables={SHARING_TABLE=${SHARING_TABLE}}" > /dev/null

echo "[INFO] Request Interceptor Private Sharing deployed"

# 5. Response Interceptor (Basic)
echo "[STEP 5/6] Deploying Response Interceptor (Basic)..."
cd $COOKBOOK_DIR/response-interceptor
zip -q interceptor_basic.zip interceptor_basic.py

aws lambda create-function \
  --function-name "${PROJECT_PREFIX}-response-interceptor-basic" \
  --region $AWS_REGION \
  --runtime python3.12 \
  --role $LAMBDA_ROLE_ARN \
  --handler interceptor_basic.lambda_handler \
  --zip-file fileb://interceptor_basic.zip \
  --timeout 30 \
  --layers $PYJWT_LAYER_ARN \
  --environment "Variables={JWKS_URL=${JWKS_URL},CLIENT_ID=${CLIENT_ID}}" 2>/dev/null || \
aws lambda update-function-code \
  --function-name "${PROJECT_PREFIX}-response-interceptor-basic" \
  --region $AWS_REGION \
  --zip-file fileb://interceptor_basic.zip > /dev/null && \
aws lambda update-function-configuration \
  --function-name "${PROJECT_PREFIX}-response-interceptor-basic" \
  --region $AWS_REGION \
  --environment "Variables={JWKS_URL=${JWKS_URL},CLIENT_ID=${CLIENT_ID}}" > /dev/null

echo "[INFO] Response Interceptor Basic deployed"

# 6. Pre Token Generation Lambda
echo "[STEP 6/6] Deploying Pre Token Generation Lambda..."
cd $COOKBOOK_DIR/pre-token-generation
zip -q pre_token_gen_v2.zip pre_token_gen_v2.py

aws lambda create-function \
  --function-name "${PROJECT_PREFIX}-pre-token-gen-v2" \
  --region $AWS_REGION \
  --runtime python3.12 \
  --role $LAMBDA_ROLE_ARN \
  --handler pre_token_gen_v2.lambda_handler \
  --zip-file fileb://pre_token_gen_v2.zip \
  --timeout 30 \
  --environment "Variables={AUTH_POLICY_TABLE=${AUTH_POLICY_TABLE}}" 2>/dev/null || \
aws lambda update-function-code \
  --function-name "${PROJECT_PREFIX}-pre-token-gen-v2" \
  --region $AWS_REGION \
  --zip-file fileb://pre_token_gen_v2.zip > /dev/null && \
aws lambda update-function-configuration \
  --function-name "${PROJECT_PREFIX}-pre-token-gen-v2" \
  --region $AWS_REGION \
  --environment "Variables={AUTH_POLICY_TABLE=${AUTH_POLICY_TABLE}}" > /dev/null

echo "[INFO] Pre Token Generation Lambda deployed"

# Cognito トリガーの設定
echo "[INFO] Configuring Cognito Pre Token Generation trigger..."
PRE_TOKEN_LAMBDA_ARN="arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:${PROJECT_PREFIX}-pre-token-gen-v2"

aws lambda add-permission \
  --function-name "${PROJECT_PREFIX}-pre-token-gen-v2" \
  --region $AWS_REGION \
  --statement-id AllowCognitoInvoke \
  --action lambda:InvokeFunction \
  --principal cognito-idp.amazonaws.com \
  --source-arn "arn:aws:cognito-idp:${AWS_REGION}:${AWS_ACCOUNT_ID}:userpool/${USER_POOL_ID}" 2>/dev/null || true

aws cognito-idp update-user-pool \
  --user-pool-id $USER_POOL_ID \
  --region $AWS_REGION \
  --lambda-config "PreTokenGenerationConfig={LambdaVersion=V2_0,LambdaArn=${PRE_TOKEN_LAMBDA_ARN}}" > /dev/null

echo ""
echo "[SUCCESS] All Lambda functions deployed!"
echo ""
echo "Deployed functions:"
echo "  - ${PROJECT_PREFIX}-authorizer-basic"
echo "  - ${PROJECT_PREFIX}-authorizer-saas"
echo "  - ${PROJECT_PREFIX}-request-interceptor-basic"
echo "  - ${PROJECT_PREFIX}-request-interceptor-sharing"
echo "  - ${PROJECT_PREFIX}-response-interceptor-basic"
echo "  - ${PROJECT_PREFIX}-pre-token-gen-v2"
echo ""
echo "Next step: Run E2E tests with python e2e-test.py"
echo ""
