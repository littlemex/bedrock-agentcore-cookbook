#!/bin/bash
# E2E検証を実行するメインスクリプト
# Usage: ./run-e2e-verification.sh [region] [prefix]

set -e

REGION=${1:-us-east-1}
PREFIX=${2:-agentcore-auth-test}

echo "=================================================="
echo "AgentCore Auth E2E Verification"
echo "=================================================="
echo "Region: $REGION"
echo "Prefix: $PREFIX"
echo ""

# Step 1: Python依存関係のインストール
echo "[STEP 1/4] Installing Python dependencies..."
pip install -q -r requirements.txt
echo "[OK] Dependencies installed"
echo ""

# Step 2: インフラストラクチャのセットアップ
echo "[STEP 2/4] Setting up infrastructure..."
chmod +x setup-infrastructure.sh
./setup-infrastructure.sh $REGION $PREFIX

if [ ! -f .env ]; then
    echo "[ERROR] Infrastructure setup failed. .env file not created."
    exit 1
fi

echo "[OK] Infrastructure setup completed"
echo ""

# Step 3: Lambda関数のデプロイ
echo "[STEP 3/4] Deploying Lambda functions..."
chmod +x deploy-lambda-functions.sh
./deploy-lambda-functions.sh

echo "[OK] Lambda functions deployed"
echo ""

# Step 4: E2Eテストの実行
echo "[STEP 4/4] Running E2E tests..."
chmod +x e2e-test.py
python3 e2e-test.py

TEST_EXIT_CODE=$?

echo ""
echo "=================================================="
echo "E2E Verification Completed"
echo "=================================================="

if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo "[SUCCESS] All tests passed!"
else
    echo "[WARNING] Some tests failed. See output above for details."
fi

echo ""
echo "Configuration saved to: .env"
echo "To re-run tests only: python3 e2e-test.py"
echo "To clean up: ./cleanup.sh"
echo ""

exit $TEST_EXIT_CODE
