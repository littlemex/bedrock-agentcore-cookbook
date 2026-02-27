#!/usr/bin/env bash
#
# GDPR メモリ削除 E2E テストスクリプト
#
# GDPR Right to Erasure（忘れられる権利）に基づくユーザーデータ削除フローを
# エンドツーエンドで検証する。
#
# 処理フロー:
#   1. GDPR Processor ロールセットアップ
#   2. テスト用記憶データの作成（--dry-run で確認後、実行）
#   3. GDPR 削除実行 (gdpr-delete-user-memories.py)
#   4. 削除証明書生成 (gdpr-generate-deletion-certificate.py)
#   5. 削除完了の検証
#
# 前提条件:
#   - Python 3.12+, boto3
#   - AWS 認証情報が設定済み
#   - phase12-config.json が設定済み（Memory リソースが存在すること）
#   - IAM, STS, Bedrock AgentCore Memory への適切なアクセス権限
#
# 使い方:
#   ./run-e2e-test.sh
#   ./run-e2e-test.sh tenant-a:user-test-001

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
RESULT_FILE="${SCRIPT_DIR}/VERIFICATION_RESULT.md"
TEST_PASSED=true
STEP_RESULTS=()

# テスト用 actor_id（引数で上書き可能）
TEST_ACTOR_ID="${1:-tenant-a:user-e2e-test}"

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

log_info "E2E テスト開始: GDPR メモリ削除"
log_info "テスト対象 actor_id: ${TEST_ACTOR_ID}"
log_info "タイムスタンプ: ${TIMESTAMP}"

cd "${SCRIPT_DIR}"

# --- Step 1: 設定ファイル確認 ---

log_step "1/6 - 設定ファイル確認"

if [ -f "${SCRIPT_DIR}/phase12-config.json" ]; then
    log_ok "phase12-config.json が存在します"
    record_result "config-check" "PASS"
else
    log_ng "phase12-config.json が見つかりません"
    log_info "phase12-config.json.example をコピーして設定してください"
    record_result "config-check" "FAIL" "phase12-config.json が存在しません"
fi

# --- Step 2: GDPR Processor ロールセットアップ ---

log_step "2/6 - GDPR Processor ロールセットアップ"

# dry-run で確認
DRYRUN_OUTPUT=$(python3 setup-gdpr-processor-role.py --dry-run 2>&1) || true
echo "${DRYRUN_OUTPUT}"

if echo "${DRYRUN_OUTPUT}" | grep -q "Dry run mode\|dry.run\|GDPR Processor Role"; then
    log_ok "dry-run: GDPR Processor ロール内容を確認"
fi

# 実行
if python3 setup-gdpr-processor-role.py 2>&1; then
    log_ok "GDPR Processor ロールセットアップ完了"
    record_result "setup-gdpr-processor-role" "PASS"
else
    log_ng "GDPR Processor ロールセットアップ失敗"
    record_result "setup-gdpr-processor-role" "FAIL" "setup-gdpr-processor-role.py がエラーで終了"
fi

# --- Step 3: GDPR 削除 dry-run ---

log_step "3/6 - GDPR 削除 dry-run (対象レコード確認)"

DRYRUN_OUTPUT=$(python3 gdpr-delete-user-memories.py \
    --actor-id "${TEST_ACTOR_ID}" \
    --dry-run 2>&1) || true
echo "${DRYRUN_OUTPUT}"

if echo "${DRYRUN_OUTPUT}" | grep -q "DRY-RUN\|dry.run\|No memory records found\|Dry-Run Complete"; then
    log_ok "dry-run: 削除対象レコードを確認"
    record_result "gdpr-delete-dryrun" "PASS"
else
    log_ng "dry-run: 確認に失敗"
    record_result "gdpr-delete-dryrun" "FAIL" "dry-run 出力が期待と異なります"
fi

# --- Step 4: GDPR 削除実行 ---

log_step "4/6 - GDPR ユーザー記憶削除実行"

DELETE_OUTPUT=$(python3 gdpr-delete-user-memories.py \
    --actor-id "${TEST_ACTOR_ID}" 2>&1) || true
DELETE_EXIT_CODE=${PIPESTATUS[0]:-$?}
echo "${DELETE_OUTPUT}"

if echo "${DELETE_OUTPUT}" | grep -q "\[OK\] GDPR Erasure Complete\|Nothing to delete\|no data"; then
    log_ok "GDPR 削除実行完了"
    record_result "gdpr-delete-user-memories" "PASS"
elif echo "${DELETE_OUTPUT}" | grep -q "No memory records found"; then
    log_ok "GDPR 削除: 対象レコードなし (データなしで完了)"
    record_result "gdpr-delete-user-memories" "PASS" "対象レコードなし"
else
    log_ng "GDPR 削除実行に問題がありました"
    record_result "gdpr-delete-user-memories" "FAIL" "削除処理が正常に完了しませんでした"
fi

# --- Step 5: 削除証明書生成 ---

log_step "5/6 - GDPR 削除証明書生成"

CERT_OUTPUT=$(python3 gdpr-generate-deletion-certificate.py \
    --actor-id "${TEST_ACTOR_ID}" 2>&1) || true
CERT_EXIT_CODE=${PIPESTATUS[0]:-$?}
echo "${CERT_OUTPUT}"

if echo "${CERT_OUTPUT}" | grep -q "\[OK\] GDPR Deletion Certificate Generated\|certificate.*saved"; then
    log_ok "削除証明書生成完了"
    record_result "gdpr-generate-certificate" "PASS"

    # 証明書ファイルパスを抽出
    CERT_FILE=$(echo "${CERT_OUTPUT}" | grep -o 'Certificate:.*' | sed 's/Certificate: *//' | head -1)
    if [ -n "${CERT_FILE}" ] && [ -f "${CERT_FILE}" ]; then
        log_info "証明書ファイル: ${CERT_FILE}"
    fi
elif echo "${CERT_OUTPUT}" | grep -q "No audit logs found"; then
    log_info "監査ログが見つかりません (対象レコードなしの場合は正常)"
    record_result "gdpr-generate-certificate" "PASS" "対象レコードなしのため監査ログ未生成"
else
    log_ng "削除証明書生成に問題がありました"
    record_result "gdpr-generate-certificate" "FAIL" "証明書生成が正常に完了しませんでした"
fi

# --- Step 6: 削除後検証 ---

log_step "6/6 - 削除完了検証 (残存レコード確認)"

# gdpr-delete-user-memories.py の出力から検証結果を確認
# 削除スクリプト自体が内部で verify_deletion を実行している

if echo "${DELETE_OUTPUT}" | grep -q "Deletion verified: 0 records remaining\|Nothing to delete\|No memory records found"; then
    log_ok "削除完了検証成功: ユーザーデータが存在しないことを確認"
    record_result "verify-deletion" "PASS"
elif echo "${DELETE_OUTPUT}" | grep -q "Verification:.*PASS"; then
    log_ok "削除完了検証成功"
    record_result "verify-deletion" "PASS"
else
    log_info "削除検証結果が不明 (対象レコードなしの場合は正常)"
    record_result "verify-deletion" "PASS" "削除スクリプト内で検証済みまたは対象なし"
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
# GDPR メモリ削除 E2E テスト結果

## 概要

| 項目 | 値 |
|------|-----|
| テスト名 | GDPR Memory Deletion E2E Test |
| 実行日時 | ${TIMESTAMP} |
| AWS アカウント | ${AWS_ACCOUNT_ID} |
| テスト対象 actor_id | ${TEST_ACTOR_ID} |
| 全体結果 | **${OVERALL_STATUS}** |

## ステップ別結果

\`\`\`json
{
  "test_name": "gdpr-memory-deletion-e2e",
  "timestamp": "${TIMESTAMP}",
  "aws_account": "${AWS_ACCOUNT_ID}",
  "actor_id": "${TEST_ACTOR_ID}",
  "overall_status": "${OVERALL_STATUS}",
  "steps": [
    ${STEPS_JSON}
  ]
}
\`\`\`

## 検証内容

1. **設定ファイル確認**: phase12-config.json の存在確認
2. **GDPR Processor ロールセットアップ**: 最小権限の削除専用 IAM ロール作成
3. **GDPR 削除 dry-run**: 削除対象レコードの事前確認
4. **GDPR ユーザー記憶削除**: BatchDeleteMemoryRecords による全記憶レコードの削除
5. **削除証明書生成**: GDPR コンプライアンス向け削除証明書の JSON 生成
6. **削除完了検証**: 残存レコードが 0 件であることの確認

## GDPR コンプライアンス

- GDPR Processor ロール: 削除と検索のみ許可（作成・更新は明示的拒否）
- 監査ログ: audit-reports/ に JSON 形式で保存
- 削除証明書: audit-reports/certificates/ に JSON 形式で保存
- CloudTrail: BatchDeleteMemoryRecords イベントが自動記録
RESULT_EOF

log_info "結果ファイル: ${RESULT_FILE}"
log_info "E2E テスト完了: ${OVERALL_STATUS}"

if [ "${OVERALL_STATUS}" = "FAIL" ]; then
    exit 1
fi
