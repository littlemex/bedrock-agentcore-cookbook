#!/usr/bin/env python3
"""
Memory ResourceTag ABAC 統合テストスクリプト

5 つのテストケースを実行して、aws:ResourceTag/tenant_id ベースの
Memory ABAC を検証する。

Test 1: Tenant A が自身の Memory にアクセス成功
Test 2: Tenant B が自身の Memory にアクセス成功
Test 3: Tenant A が Tenant B の Memory にアクセス拒否（ResourceTag 不一致）
Test 4: Tenant B が Tenant A の Memory にアクセス拒否（ResourceTag 不一致）
Test 5: ResourceTag なしの Memory へのアクセス拒否（Null Condition 検証）

使用する API:
- STS AssumeRole (SessionTags で tenant_id を付与)
- Memory PutMemoryRecord / RetrieveMemoryRecords
"""

import boto3
import json
import os
import sys
import time
import uuid
from datetime import datetime
from botocore.exceptions import ClientError

REGION = "us-east-1"
CONFIG_FILE = "phase15-config.json"
RESULT_FILE = "VERIFICATION_RESULT.md"


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Config file not found: {CONFIG_FILE}")
        print("  Run: python3 setup-memory-with-tags.py && python3 setup-iam-roles-with-resource-tag.py first")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)

    # 必須フィールドの検証
    required = ["memoryA", "memoryB", "roles"]
    for field in required:
        if field not in config:
            print(f"[ERROR] Missing required field in config: {field}")
            sys.exit(1)

    return config


def assume_role_with_tags(role_arn, external_id, tenant_id):
    """
    STS AssumeRole を実行し、SessionTags で tenant_id を付与する。

    返り値は tenant_id タグ付きの一時的な認証情報を持つ
    bedrock-agentcore クライアント。
    """
    sts = boto3.client("sts", region_name=REGION)
    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=f"restag-abac-test-{tenant_id}-{uuid.uuid4().hex[:8]}",
        ExternalId=external_id,
        Tags=[{"Key": "tenant_id", "Value": tenant_id}],
    )
    credentials = response["Credentials"]

    # Data Plane クライアント (Memory Record 操作用)
    client = boto3.client(
        "bedrock-agentcore",
        region_name=REGION,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )
    return client


def test_put_memory_record(client, memory_id, strategy_id, tenant_id, namespace):
    """
    PutMemoryRecord (BatchCreateMemoryRecords) を実行する。

    返り値: (success: bool, detail: str)
    """
    request_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat() + "Z"

    try:
        client.batch_create_memory_records(
            memoryId=memory_id,
            memoryRecords=[
                {
                    "content": {
                        "text": f"Test record for ResourceTag ABAC by {tenant_id}. Timestamp: {timestamp}"
                    },
                    "namespaces": [namespace],
                    "memoryStrategyId": strategy_id,
                }
            ],
        )
        return True, "BatchCreateMemoryRecords succeeded"
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        return False, f"{error_code}: {error_msg}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def test_retrieve_memory_records(client, memory_id, strategy_id, namespace, query):
    """
    RetrieveMemoryRecords を実行する。

    返り値: (success: bool, detail: str)
    """
    try:
        response = client.retrieve_memory_records(
            memoryId=memory_id,
            memoryStrategyId=strategy_id,
            namespace=namespace,
            query={
                "text": query,
            },
        )
        records = response.get("memoryRecords", [])
        return True, f"RetrieveMemoryRecords succeeded, {len(records)} records found"
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        return False, f"{error_code}: {error_msg}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def run_test_case(test_num, description, client, memory_id, strategy_id,
                  tenant_id, namespace, expect_success):
    """
    1 つのテストケースを実行する。

    PutMemoryRecord と RetrieveMemoryRecords の両方をテストし、
    期待結果と照合する。
    """
    print(f"\n{'=' * 60}")
    print(f"[TEST {test_num}] {description}")
    print(f"{'=' * 60}")
    print(f"  Tenant: {tenant_id}")
    print(f"  Memory ID: {memory_id}")
    print(f"  Strategy ID: {strategy_id}")
    print(f"  Namespace: {namespace}")
    print(f"  Expected: {'SUCCESS' if expect_success else 'DENIED'}")

    results = []

    # Test: BatchCreateMemoryRecords
    print(f"\n  [Sub-test] BatchCreateMemoryRecords...")
    success, detail = test_put_memory_record(
        client, memory_id, strategy_id, tenant_id, namespace
    )
    if success == expect_success:
        status = "PASS"
    else:
        status = "FAIL"
    print(f"  [{status}] {detail}")
    results.append({
        "operation": "BatchCreateMemoryRecords",
        "success": success,
        "expected_success": expect_success,
        "status": status,
        "detail": detail,
    })

    # Test: RetrieveMemoryRecords
    print(f"\n  [Sub-test] RetrieveMemoryRecords...")
    success, detail = test_retrieve_memory_records(
        client, memory_id, strategy_id, namespace, f"test query from {tenant_id}"
    )
    if success == expect_success:
        status = "PASS"
    else:
        status = "FAIL"
    print(f"  [{status}] {detail}")
    results.append({
        "operation": "RetrieveMemoryRecords",
        "success": success,
        "expected_success": expect_success,
        "status": status,
        "detail": detail,
    })

    return results


def run_all_tests(config):
    """5 つのテストケースを実行"""
    memory_a = config["memoryA"]
    memory_b = config["memoryB"]
    memory_no_tag = config.get("memoryNoTag")
    role_a = config["roles"]["tenantA"]
    role_b = config["roles"]["tenantB"]

    all_results = []

    # AssumeRole: Tenant A
    print("\n[INFO] AssumeRole for Tenant A...")
    try:
        client_a = assume_role_with_tags(
            role_a["roleArn"], "tenant-a", "tenant-a"
        )
        print(f"[OK] Tenant A session established (PrincipalTag/tenant_id=tenant-a)")
    except ClientError as e:
        print(f"[ERROR] AssumeRole failed for Tenant A: {e}")
        return []

    # AssumeRole: Tenant B
    print("\n[INFO] AssumeRole for Tenant B...")
    try:
        client_b = assume_role_with_tags(
            role_b["roleArn"], "tenant-b", "tenant-b"
        )
        print(f"[OK] Tenant B session established (PrincipalTag/tenant_id=tenant-b)")
    except ClientError as e:
        print(f"[ERROR] AssumeRole failed for Tenant B: {e}")
        return []

    # Test 1: Tenant A -> Memory A (expect SUCCESS)
    results_1 = run_test_case(
        test_num=1,
        description="Tenant A accessing own Memory (expect SUCCESS)",
        client=client_a,
        memory_id=memory_a["memoryId"],
        strategy_id=memory_a["strategyId"],
        tenant_id="tenant-a",
        namespace="/tenant-a/test/",
        expect_success=True,
    )
    all_results.append(("Test 1: Tenant A -> Memory A (own)", results_1))

    # Test 2: Tenant B -> Memory B (expect SUCCESS)
    results_2 = run_test_case(
        test_num=2,
        description="Tenant B accessing own Memory (expect SUCCESS)",
        client=client_b,
        memory_id=memory_b["memoryId"],
        strategy_id=memory_b["strategyId"],
        tenant_id="tenant-b",
        namespace="/tenant-b/test/",
        expect_success=True,
    )
    all_results.append(("Test 2: Tenant B -> Memory B (own)", results_2))

    # Test 3: Tenant A -> Memory B (expect DENIED)
    results_3 = run_test_case(
        test_num=3,
        description="Tenant A accessing Tenant B Memory (expect DENIED, ResourceTag mismatch)",
        client=client_a,
        memory_id=memory_b["memoryId"],
        strategy_id=memory_b["strategyId"],
        tenant_id="tenant-a",
        namespace="/tenant-a/cross-test/",
        expect_success=False,
    )
    all_results.append(("Test 3: Tenant A -> Memory B (cross-tenant)", results_3))

    # Test 4: Tenant B -> Memory A (expect DENIED)
    results_4 = run_test_case(
        test_num=4,
        description="Tenant B accessing Tenant A Memory (expect DENIED, ResourceTag mismatch)",
        client=client_b,
        memory_id=memory_a["memoryId"],
        strategy_id=memory_a["strategyId"],
        tenant_id="tenant-b",
        namespace="/tenant-b/cross-test/",
        expect_success=False,
    )
    all_results.append(("Test 4: Tenant B -> Memory A (cross-tenant)", results_4))

    # Test 5: Tenant A -> Memory without tags (expect DENIED, Null Condition)
    if memory_no_tag and memory_no_tag.get("memoryId"):
        results_5 = run_test_case(
            test_num=5,
            description="Tenant A accessing untagged Memory (expect DENIED, Null Condition)",
            client=client_a,
            memory_id=memory_no_tag["memoryId"],
            strategy_id=memory_no_tag["strategyId"],
            tenant_id="tenant-a",
            namespace="/tenant-a/null-test/",
            expect_success=False,
        )
        all_results.append(("Test 5: Tenant A -> No-tag Memory (Null Condition)", results_5))
    else:
        print("\n[SKIP] Test 5: memoryNoTag not found in config, skipping Null Condition test")

    return all_results


def print_summary(all_results):
    """テスト結果のサマリを表示"""
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)

    total_pass = 0
    total_fail = 0
    blocked = False

    for test_name, results in all_results:
        print(f"\n  {test_name}:")
        for r in results:
            status = r["status"]
            if status == "PASS":
                total_pass += 1
            else:
                total_fail += 1
            print(f"    [{status}] {r['operation']}: {r['detail']}")

            # BLOCKED 判定: AccessDeniedException 以外のエラーで失敗した場合
            if r["status"] == "FAIL" and r["expected_success"]:
                if "not supported" in r["detail"].lower() or \
                   "unknown" in r["detail"].lower() or \
                   "not authorized" in r["detail"].lower():
                    blocked = True

    total = total_pass + total_fail
    print(f"\n{'=' * 60}")
    print(f"Total: {total} | Passed: {total_pass} | Failed: {total_fail}")

    if blocked:
        print(f"\n[BLOCKED] aws:ResourceTag/tenant_id may not be supported for Memory API.")
        print(f"  See VERIFICATION_RESULT.md for details and alternatives.")
        return "BLOCKED"
    elif total_fail == 0:
        print(f"\n[OK] All tests passed! Memory ResourceTag ABAC is working correctly.")
        return "PASS"
    else:
        print(f"\n[FAIL] {total_fail} test(s) failed. See details above.")
        return "FAIL"


def write_verification_result(all_results, overall_status):
    """検証結果を VERIFICATION_RESULT.md に出力"""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# Memory ResourceTag ABAC 検証結果",
        "",
        f"**検証日時**: {timestamp}",
        f"**全体ステータス**: [{overall_status}]",
        "",
        "## 検証した Condition Key",
        "",
        "```",
        "aws:ResourceTag/tenant_id == ${aws:PrincipalTag/tenant_id}",
        "```",
        "",
        "## テスト結果",
        "",
        "| Test | 説明 | 操作 | 期待結果 | 実際の結果 | ステータス |",
        "|------|------|------|---------|-----------|----------|",
    ]

    for test_name, results in all_results:
        for r in results:
            expected = "成功" if r["expected_success"] else "拒否"
            actual = "成功" if r["success"] else "拒否/エラー"
            lines.append(
                f"| {test_name} | {r['operation']} | {r['operation']} | {expected} | {actual} | {r['status']} |"
            )

    lines.extend([
        "",
        "## 詳細ログ",
        "",
    ])

    for test_name, results in all_results:
        lines.append(f"### {test_name}")
        lines.append("")
        for r in results:
            lines.append(f"- **{r['operation']}**: [{r['status']}] {r['detail']}")
        lines.append("")

    if overall_status == "BLOCKED":
        lines.extend([
            "## BLOCKED: 代替案",
            "",
            "`aws:ResourceTag/tenant_id` が Memory API で動作しない場合の代替策:",
            "",
            "### 代替案 1: bedrock-agentcore:namespace Condition Key",
            "",
            "Example 02 で検証済みの `bedrock-agentcore:namespace` を使用する。",
            "namespace パスにテナント ID を埋め込むことで、テナント分離を実現。",
            "",
            "```json",
            '{',
            '  "Effect": "Allow",',
            '  "Action": ["bedrock-agentcore:BatchCreateMemoryRecords"],',
            '  "Resource": "arn:aws:bedrock-agentcore:*:*:memory/*",',
            '  "Condition": {',
            '    "StringLike": {',
            '      "bedrock-agentcore:namespace": "/${aws:PrincipalTag/tenant_id}/*"',
            '    }',
            '  }',
            '}',
            "```",
            "",
            "### 代替案 2: テナント別 Memory リソース + リソースベースポリシー",
            "",
            "テナントごとに個別の Memory リソースを作成し、",
            "IAM ポリシーの Resource 句で Memory ARN を直接指定する。",
            "",
            "```json",
            '{',
            '  "Effect": "Allow",',
            '  "Action": ["bedrock-agentcore:BatchCreateMemoryRecords"],',
            '  "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-tenant-a-xxx"',
            '}',
            "```",
            "",
            "### 代替案 3: namespace + ResourceTag の組み合わせ",
            "",
            "namespace Condition Key を主制御として使用し、",
            "将来 ResourceTag がサポートされた際に多層防御として追加する。",
            "",
        ])

    if overall_status == "PASS":
        lines.extend([
            "## 結論",
            "",
            "`aws:ResourceTag/tenant_id` は Memory API で正常に動作します。",
            "S3 の `s3:ExistingObjectTag/tenant_id` と同様のパターンで、",
            "Memory リソースのテナント分離を IAM レベルで実現できます。",
            "",
            "### S3 ABAC との比較",
            "",
            "| 項目 | S3 ABAC (Example 11) | Memory ResourceTag ABAC (Example 15) |",
            "|------|---------------------|--------------------------------------|",
            "| Condition Key | `s3:ExistingObjectTag/tenant_id` | `aws:ResourceTag/tenant_id` |",
            "| タグ対象 | S3 オブジェクト | Memory リソース |",
            "| タグ付与方法 | PutObjectTagging | TagResource |",
            "| 粒度 | オブジェクトレベル | リソース（Memory）レベル |",
            "",
        ])

    lines.extend([
        "## 関連する Example",
        "",
        "- **Example 02**: IAM ABAC (namespace Condition Key)",
        "- **Example 11**: S3 ABAC (s3:ExistingObjectTag/tenant_id)",
        "- **Example 05**: End-to-End (STS SessionTags)",
    ])

    with open(RESULT_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n[OK] Verification result saved: {os.path.abspath(RESULT_FILE)}")


def main():
    print("=" * 60)
    print("Memory ResourceTag ABAC Integration Tests")
    print("=" * 60)

    config = load_config()

    print(f"[INFO] Memory A: {config['memoryA']['memoryId']} (tenant-a)")
    print(f"[INFO] Memory B: {config['memoryB']['memoryId']} (tenant-b)")
    mem_no_tag = config.get("memoryNoTag", {})
    if mem_no_tag.get("memoryId"):
        print(f"[INFO] Memory (no tag): {mem_no_tag['memoryId']} (Null Condition test)")
    print(f"[INFO] Role A: {config['roles']['tenantA']['roleName']}")
    print(f"[INFO] Role B: {config['roles']['tenantB']['roleName']}")

    all_results = run_all_tests(config)

    if not all_results:
        print("\n[ERROR] No test results. Check AssumeRole configuration.")
        sys.exit(1)

    overall_status = print_summary(all_results)
    write_verification_result(all_results, overall_status)

    if overall_status == "PASS":
        sys.exit(0)
    elif overall_status == "BLOCKED":
        sys.exit(2)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
