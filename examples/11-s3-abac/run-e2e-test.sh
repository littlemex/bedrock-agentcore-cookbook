#!/usr/bin/env bash
#
# S3 ABAC E2E テストスクリプト
#
# S3 オブジェクトタグと STS セッションタグを使用した ABAC パターンを
# エンドツーエンドで検証する。テナント間のデータ分離が正しく機能していることを確認する。
#
# テストシナリオ:
#   Test 1: Tenant A が自身のオブジェクトにアクセス成功
#   Test 2: Tenant B が自身のオブジェクトにアクセス成功
#   Test 3: Tenant A が Tenant B のオブジェクトにアクセス拒否
#   Test 4: Tenant B が Tenant A のオブジェクトにアクセス拒否
#
# 前提条件:
#   - Python 3.12+, boto3
#   - AWS 認証情報が設定済み
#   - S3, IAM, STS へのアクセス権限
#
# 使い方:
#   ./run-e2e-test.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
RESULT_FILE="${SCRIPT_DIR}/VERIFICATION_RESULT.md"
TEST_PASSED=true
STEP_RESULTS=()

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

log_info "E2E テスト開始: S3 ABAC"
log_info "タイムスタンプ: ${TIMESTAMP}"

# --- Step 1: S3 バケットセットアップ ---

log_step "1/5 - S3 バケットセットアップ (dry-run)"

cd "${SCRIPT_DIR}"

DRYRUN_OUTPUT=$(python3 setup-s3-buckets.py --dry-run 2>&1) || true
echo "${DRYRUN_OUTPUT}"

if echo "${DRYRUN_OUTPUT}" | grep -q "Dry run mode\|dry.run\|Bucket"; then
    log_ok "dry-run: セットアップ内容を確認"
    record_result "setup-s3-buckets-dryrun" "PASS"
else
    log_ng "dry-run: 確認に失敗"
    record_result "setup-s3-buckets-dryrun" "FAIL" "dry-run 出力が期待と異なります"
fi

log_step "2/5 - S3 バケット作成・オブジェクトアップロード"

if python3 setup-s3-buckets.py 2>&1; then
    log_ok "S3 バケットセットアップ完了"
    record_result "setup-s3-buckets" "PASS"
else
    log_ng "S3 バケットセットアップ失敗"
    record_result "setup-s3-buckets" "FAIL" "setup-s3-buckets.py がエラーで終了"
fi

# --- Step 2: IAM ロールセットアップ ---

log_step "3/5 - IAM ロールセットアップ"

if python3 setup-iam-roles.py 2>&1; then
    log_ok "IAM ロールセットアップ完了"
    record_result "setup-iam-roles" "PASS"

    # IAM ポリシー伝播を待機
    log_info "IAM ポリシー伝播を待機中 (10 秒)..."
    sleep 10
else
    log_ng "IAM ロールセットアップ失敗"
    record_result "setup-iam-roles" "FAIL" "setup-iam-roles.py がエラーで終了"
fi

# --- Step 3: ABAC テスト実行 ---

log_step "4/5 - S3 ABAC テスト実行 (4 テストケース)"

TEST_OUTPUT=$(python3 test-s3-abac.py 2>&1) || true
TEST_EXIT_CODE=${PIPESTATUS[0]:-$?}
echo "${TEST_OUTPUT}"

if echo "${TEST_OUTPUT}" | grep -q "\[OK\] All tests passed"; then
    log_ok "S3 ABAC テスト: 全テスト成功"
    record_result "test-s3-abac" "PASS" "4 テストケース全て PASS"
else
    # 個別テスト結果を集計
    PASS_COUNT=$(echo "${TEST_OUTPUT}" | grep -c "\[PASS\]" || true)
    FAIL_COUNT=$(echo "${TEST_OUTPUT}" | grep -c "\[FAIL\]" || true)
    log_ng "S3 ABAC テスト: PASS=${PASS_COUNT}, FAIL=${FAIL_COUNT}"
    record_result "test-s3-abac" "FAIL" "PASS=${PASS_COUNT}, FAIL=${FAIL_COUNT}"
fi

# --- Step 4: クリーンアップ ---

log_step "5/5 - リソースクリーンアップ"

if python3 cleanup-s3-resources.py 2>&1; then
    log_ok "リソースクリーンアップ完了"
    record_result "cleanup-s3-resources" "PASS"
else
    log_ng "リソースクリーンアップ失敗 (テスト結果には影響しません)"
    record_result "cleanup-s3-resources" "WARN" "クリーンアップが完全に完了しませんでした"
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
# S3 ABAC E2E テスト結果

## 概要

| 項目 | 値 |
|------|-----|
| テスト名 | S3 ABAC E2E Test |
| 実行日時 | ${TIMESTAMP} |
| AWS アカウント | ${AWS_ACCOUNT_ID} |
| 全体結果 | **${OVERALL_STATUS}** |

## ステップ別結果

\`\`\`json
{
  "test_name": "s3-abac-e2e",
  "timestamp": "${TIMESTAMP}",
  "aws_account": "${AWS_ACCOUNT_ID}",
  "overall_status": "${OVERALL_STATUS}",
  "steps": [
    ${STEPS_JSON}
  ]
}
\`\`\`

## 検証内容

1. **S3 バケットセットアップ (dry-run)**: セットアップ内容の事前確認
2. **S3 バケット作成**: テナント別 S3 オブジェクトの作成とタグ付け
3. **IAM ロールセットアップ**: ABAC ポリシー付き IAM ロールの作成 (Tenant A/B)
4. **S3 ABAC テスト**: 4 テストケースの実行
   - Test 1: Tenant A が自身のオブジェクトにアクセス成功
   - Test 2: Tenant B が自身のオブジェクトにアクセス成功
   - Test 3: Tenant A が Tenant B のオブジェクトにアクセス拒否
   - Test 4: Tenant B が Tenant A のオブジェクトにアクセス拒否
5. **リソースクリーンアップ**: S3 バケット・IAM ロール・設定ファイルの削除
RESULT_EOF

log_info "結果ファイル: ${RESULT_FILE}"
log_info "E2E テスト完了: ${OVERALL_STATUS}"

if [ "${OVERALL_STATUS}" = "FAIL" ]; then
    exit 1
fi
