#!/bin/bash
#
# Run all E2E verification tests for Inbound/Outbound Auth
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "E2E Verification Tests - Inbound/Outbound Auth"
echo "============================================================"
echo ""

# Load environment variables
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Function to run test and track results
run_test() {
    local test_name=$1
    local test_file=$2

    echo ""
    echo "------------------------------------------------------------"
    echo "Running: $test_name"
    echo "------------------------------------------------------------"

    if python3 "$test_file"; then
        echo "[OK] $test_name PASSED"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        echo "[FAIL] $test_name FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi

    TOTAL_TESTS=$((TOTAL_TESTS + 1))
}

# Phase 1 - CRITICAL
echo ""
echo "=== PHASE 1 - CRITICAL ==="
run_test "Inbound Auth Integration Flow" "tests/test_inbound_auth.py"
run_test "Outbound Auth - Secrets Manager" "tests/test_outbound_auth_secrets_manager.py"
run_test "Memory API ABAC" "tests/test_memory_api_abac.py"

# Phase 2 - HIGH
echo ""
echo "=== PHASE 2 - HIGH ==="
run_test "Dual Auth Independence" "tests/test_dual_auth_independence.py"
run_test "Cognito Client Secret Rotation E2E" "tests/test_cognito_secret_rotation_e2e.py"

# Summary
echo ""
echo "============================================================"
echo "OVERALL TEST SUMMARY"
echo "============================================================"
echo "Total Tests: $TOTAL_TESTS"
echo "Passed: $PASSED_TESTS"
echo "Failed: $FAILED_TESTS"
echo "============================================================"

if [ $FAILED_TESTS -eq 0 ]; then
    echo ""
    echo "[SUCCESS] All tests passed!"
    exit 0
else
    echo ""
    echo "[FAILURE] Some tests failed."
    exit 1
fi
