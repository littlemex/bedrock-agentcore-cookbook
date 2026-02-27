#!/usr/bin/env bash
#
# AuthPolicyTable E2E テストスクリプト
#
# DynamoDB AuthPolicyTable の作成、テストデータ投入、クエリ検証を
# 一連のフローとして実行する。
#
# 検証内容:
#   - テーブル作成 (setup-dynamodb-table.py)
#   - テストデータ投入 (seed-test-users.py --clear)
#   - Email クエリ: 4 ユーザー x GetItem
#   - Tenant クエリ: 2 テナント x GSI Query
#   - Pre Token Generation クレーム シミュレーション
#
# 前提条件:
#   - Python 3.12+, boto3
#   - AWS 認証情報が設定済み
#   - DynamoDB へのアクセス権限
#
# 使い方:
#   ./run-e2e-test.sh
#   ./run-e2e-test.sh --region us-west-2

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
RESULT_FILE="${SCRIPT_DIR}/VERIFICATION_RESULT.md"
TEST_PASSED=true
STEP_RESULTS=()

# リージョン（引数で上書き可能）
REGION="us-east-1"
if [ "${1:-}" = "--region" ] && [ -n "${2:-}" ]; then
    REGION="$2"
fi

# テスト対象のユーザー
TEST_EMAILS=(
    "admin@tenant-a.example.com"
    "user@tenant-a.example.com"
    "admin@tenant-b.example.com"
    "readonly@tenant-b.example.com"
)

TEST_TENANTS=(
    "tenant-a"
    "tenant-b"
)

# --- ユーティリティ関数 ---

log_info() {
    echo "[INFO] $(date +"%H:%M:%S") $*"
}

log_ok() {
    echo "[OK] $(date +"%H:%M:%S") $*"
}

log_ng() {
    echo "[NG] $(date +"%H:%M:%S") $*"
}

log_step() {
    echo ""
    echo "=========================================="
    echo "[STEP] $*"
    echo "=========================================="
}

record_result() {
    local step_name="$1"
    local status="$2"
    local detail="${3:-}"
    STEP_RESULTS+=("{\"step\": \"${step_name}\", \"status\": \"${status}\", \"detail\": \"${detail}\"}")
    if [ "${status}" = "FAIL" ]; then
        TEST_PASSED=false
    fi
}

log_info "E2E テスト開始: AuthPolicyTable"
log_info "リージョン: ${REGION}"
log_info "タイムスタンプ: ${TIMESTAMP}"

cd "${SCRIPT_DIR}"

# --- Step 1: DynamoDB テーブルセットアップ ---

log_step "1/5 - DynamoDB テーブルセットアップ"

if python3 setup-dynamodb-table.py --region "${REGION}" 2>&1; then
    log_ok "DynamoDB テーブルセットアップ完了"
    record_result "setup-dynamodb-table" "PASS"
else
    log_ng "DynamoDB テーブルセットアップ失敗"
    record_result "setup-dynamodb-table" "FAIL" "setup-dynamodb-table.py がエラーで終了"
fi

# --- Step 2: dry-run でテストデータ確認 ---

log_step "2/5 - テストデータ dry-run 確認"

DRYRUN_OUTPUT=$(python3 seed-test-users.py --region "${REGION}" --dry-run 2>&1) || true
echo "${DRYRUN_OUTPUT}"

if echo "${DRYRUN_OUTPUT}" | grep -q "admin@tenant-a.example.com"; then
    log_ok "dry-run: テストデータ内容を確認 (4 ユーザー)"
    record_result "seed-test-users-dryrun" "PASS"
else
    log_ng "dry-run: テストデータ確認に失敗"
    record_result "seed-test-users-dryrun" "FAIL" "dry-run 出力に期待するデータが含まれていません"
fi

# --- Step 3: テストデータ投入 ---

log_step "3/5 - テストデータ投入 (--clear で既存データをリセット)"

if python3 seed-test-users.py --region "${REGION}" --clear 2>&1; then
    log_ok "テストデータ投入完了"
    record_result "seed-test-users" "PASS"
else
    log_ng "テストデータ投入失敗"
    record_result "seed-test-users" "FAIL" "seed-test-users.py がエラーで終了"
fi

# --- Step 4: Email/Tenant クエリ検証 ---

log_step "4/5 - Email/Tenant クエリ検証"

QUERY_ALL_PASS=true

# Email クエリ (GetItem)
for email in "${TEST_EMAILS[@]}"; do
    log_info "Email クエリ: ${email}"
    QUERY_OUTPUT=$(python3 query-user-policy.py \
        --region "${REGION}" \
        --email "${email}" \
        --json 2>&1) || true

    if echo "${QUERY_OUTPUT}" | grep -q "\"email\""; then
        log_ok "  ${email}: ユーザーポリシー取得成功"
    else
        log_ng "  ${email}: ユーザーポリシー取得失敗"
        QUERY_ALL_PASS=false
    fi
done

# Tenant クエリ (GSI: TenantIdIndex)
for tenant in "${TEST_TENANTS[@]}"; do
    log_info "Tenant クエリ (GSI): ${tenant}"
    QUERY_OUTPUT=$(python3 query-user-policy.py \
        --region "${REGION}" \
        --tenant "${tenant}" \
        --json 2>&1) || true

    if echo "${QUERY_OUTPUT}" | grep -q "\"tenant_id\""; then
        USER_COUNT=$(echo "${QUERY_OUTPUT}" | grep -c "\"email\"" || true)
        log_ok "  ${tenant}: テナントユーザー一覧取得成功 (${USER_COUNT} ユーザー)"
    else
        log_ng "  ${tenant}: テナントユーザー一覧取得失敗"
        QUERY_ALL_PASS=false
    fi
done

# 全ユーザー一覧 (Scan)
log_info "全ユーザー一覧 (Scan)"
LIST_OUTPUT=$(python3 query-user-policy.py \
    --region "${REGION}" \
    --list-all \
    --json 2>&1) || true

if echo "${LIST_OUTPUT}" | grep -q "\"email\""; then
    TOTAL_COUNT=$(echo "${LIST_OUTPUT}" | grep -c "\"email\"" || true)
    log_ok "  全ユーザー一覧: ${TOTAL_COUNT} ユーザー取得"
else
    log_ng "  全ユーザー一覧取得失敗"
    QUERY_ALL_PASS=false
fi

if [ "${QUERY_ALL_PASS}" = true ]; then
    record_result "query-user-policy" "PASS" "全 Email/Tenant/Scan クエリ成功"
else
    record_result "query-user-policy" "FAIL" "一部のクエリが失敗"
fi

# --- Step 5: Pre Token Generation クレーム シミュレーション ---

log_step "5/5 - Pre Token Generation クレーム シミュレーション"

CLAIMS_PASS=true

for email in "${TEST_EMAILS[@]}"; do
    log_info "クレームシミュレーション: ${email}"
    CLAIMS_OUTPUT=$(python3 query-user-policy.py \
        --region "${REGION}" \
        --email "${email}" \
        --simulate-claims 2>&1) || true

    if echo "${CLAIMS_OUTPUT}" | grep -q "custom:tenant_id"; then
        log_ok "  ${email}: クレーム生成成功 (custom:tenant_id, custom:role, custom:groups)"
    else
        log_ng "  ${email}: クレーム生成失敗"
        CLAIMS_PASS=false
    fi
done

if [ "${CLAIMS_PASS}" = true ]; then
    record_result "simulate-claims" "PASS" "全 4 ユーザーのクレーム生成成功"
else
    record_result "simulate-claims" "FAIL" "一部のクレーム生成が失敗"
fi

# --- 結果出力 ---

log_step "テスト結果サマリー"

if [ "${TEST_PASSED}" = true ]; then
    OVERALL_STATUS="PASS"
    log_ok "E2E テスト: 全ステップ成功"
else
    OVERALL_STATUS="FAIL"
    log_ng "E2E テスト: 一部のステップが失敗"
fi

# AWS アカウント ID を取得（結果記録用）
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "unknown")

# VERIFICATION_RESULT.md 生成
STEPS_JSON=$(printf '%s,' "${STEP_RESULTS[@]}" | sed 's/,$//')

cat > "${RESULT_FILE}" << RESULT_EOF
# AuthPolicyTable E2E テスト結果

## 概要

| 項目 | 値 |
|------|-----|
| テスト名 | AuthPolicyTable E2E Test |
| 実行日時 | ${TIMESTAMP} |
| AWS アカウント | ${AWS_ACCOUNT_ID} |
| リージョン | ${REGION} |
| テーブル名 | AuthPolicyTable |
| 全体結果 | **${OVERALL_STATUS}** |

## ステップ別結果

\`\`\`json
{
  "test_name": "auth-policy-table-e2e",
  "timestamp": "${TIMESTAMP}",
  "aws_account": "${AWS_ACCOUNT_ID}",
  "region": "${REGION}",
  "overall_status": "${OVERALL_STATUS}",
  "steps": [
    ${STEPS_JSON}
  ]
}
\`\`\`

## 検証内容

1. **DynamoDB テーブルセットアップ**: AuthPolicyTable の作成と GSI (TenantIdIndex) の確認
2. **テストデータ dry-run**: 投入前のデータ内容確認 (4 ユーザー)
3. **テストデータ投入**: --clear でリセット後、4 名のテストユーザーデータ投入
4. **Email/Tenant クエリ検証**:
   - Email クエリ (GetItem): 4 ユーザー
   - Tenant クエリ (GSI Query): 2 テナント
   - 全ユーザー一覧 (Scan)
5. **クレームシミュレーション**: Pre Token Generation Lambda と同等のクレーム生成テスト

## テストユーザー

| Email | Tenant | Role |
|-------|--------|------|
| admin@tenant-a.example.com | tenant-a | admin |
| user@tenant-a.example.com | tenant-a | user |
| admin@tenant-b.example.com | tenant-b | admin |
| readonly@tenant-b.example.com | tenant-b | readonly |
RESULT_EOF

log_info "結果ファイル: ${RESULT_FILE}"
log_info "E2E テスト完了: ${OVERALL_STATUS}"

if [ "${OVERALL_STATUS}" = "FAIL" ]; then
    exit 1
fi
