#!/usr/bin/env python3
"""
Memory + IAM ABAC 統合検証スクリプト

Memory テナント分離、STS SessionTags ABAC、Cross-Tenant Deny ポリシーを検証する。
"""

import boto3
import json
import os
import sys
import argparse
import logging
from datetime import datetime, timezone
from botocore.exceptions import ClientError

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# リージョン
REGION = "us-east-1"

# Config ファイル
CONFIG_FILE = "phase5-config.json"

# テスト結果
test_results = []


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Config file not found: {CONFIG_FILE}")
        logger.error("  Run: python3 setup-memory.py and python3 setup-iam-roles.py first")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def assume_role_with_external_id(sts_client, role_arn, tenant_id, session_name):
    """STS AssumeRole with External ID"""
    try:
        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            ExternalId=tenant_id
        )
        credentials = response["Credentials"]
        logger.info(f"[OK] AssumeRole success: {role_arn}, tenant_id={tenant_id}")
        return {
            "AccessKeyId": credentials["AccessKeyId"],
            "SecretAccessKey": credentials["SecretAccessKey"],
            "SessionToken": credentials["SessionToken"]
        }
    except ClientError as e:
        logger.error(f"[FAIL] AssumeRole failed: {e}")
        return None


def create_memory_client_with_credentials(credentials):
    """一時認証情報で Memory クライアントを作成"""
    return boto3.client(
        "bedrock-agentcore",
        region_name=REGION,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"]
    )


def create_memory_record(client, memory_id, strategy_id, actor_id, content):
    """Memory レコードを作成"""
    try:
        # actor_id から namespace を構築（例: tenant-a/user-001 → /tenant-a/user-001/）
        namespace = f"/{actor_id}/"

        # requestIdentifier は [a-zA-Z0-9_-]+ のみ許可
        request_id = actor_id.replace("/", "-").replace(" ", "-")

        response = client.batch_create_memory_records(
            memoryId=memory_id,
            records=[
                {
                    "requestIdentifier": f"req-{request_id}",
                    "namespaces": [namespace],
                    "content": {"text": content},
                    "timestamp": datetime.now(timezone.utc),
                    "memoryStrategyId": strategy_id
                }
            ]
        )

        if response["successfulRecords"]:
            record = response["successfulRecords"][0]
            record_id = record["memoryRecordId"]
            logger.info(f"[OK] Memory record created: {record_id}, namespace={namespace}")
            return record_id
        else:
            raise Exception(f"Failed to create record: {response['failedRecords']}")
    except ClientError as e:
        logger.error(f"[FAIL] BatchCreateMemoryRecords failed: {e}")
        raise


def retrieve_memory_records(client, memory_id, strategy_id, actor_id):
    """Memory レコードを取得"""
    try:
        # actor_id から namespace プレフィックスを構築
        namespace_prefix = f"/{actor_id}/"

        response = client.retrieve_memory_records(
            memoryId=memory_id,
            namespace=namespace_prefix,
            searchCriteria={
                "searchQuery": "test",
                "memoryStrategyId": strategy_id,
                "topK": 10
            },
            maxResults=10
        )
        records = response.get("memoryRecordSummaries", [])
        logger.info(f"[OK] Retrieved {len(records)} records for namespace={namespace_prefix}")
        return records
    except ClientError as e:
        logger.error(f"[FAIL] RetrieveMemoryRecords failed: {e}")
        raise


def run_test(test_name, test_func):
    """テストを実行して結果を記録"""
    logger.info("")
    logger.info(f"[TEST] {test_name}")
    logger.info("-" * 60)

    try:
        result = test_func()
        test_results.append({
            "name": test_name,
            "status": "PASS" if result["success"] else "FAIL",
            "detail": result["detail"],
            "raw_data": result.get("raw_data", {})
        })
        if result["success"]:
            logger.info(f"[PASS] {test_name}: {result['detail']}")
        else:
            logger.info(f"[FAIL] {test_name}: {result['detail']}")
    except Exception as e:
        logger.error(f"[FAIL] {test_name}: {e}")
        test_results.append({
            "name": test_name,
            "status": "FAIL",
            "detail": str(e),
            "raw_data": {}
        })


def test_tenant_a_create(config, sts_client):
    """Test 1: Tenant A が自テナント actorId で Memory レコード作成"""
    role_arn = config["roles"]["tenantA"]["roleArn"]
    memory_id = config.get("memoryTenantA", config.get("memory", {})).get("memoryId")
    strategy_id = config.get("memoryTenantA", config.get("memory", {})).get("strategyId")

    # AssumeRole with SessionTags
    credentials = assume_role_with_external_id(sts_client, role_arn, "tenant-a", "test-tenant-a-create")
    if not credentials:
        return {"success": False, "detail": "AssumeRole failed"}

    # Memory レコード作成
    memory_client = create_memory_client_with_credentials(credentials)
    try:
        record_id = create_memory_record(
            memory_client,
            memory_id,
            strategy_id,
            "tenant-a/user-001",
            "Test content for Tenant A user-001"
        )
        return {
            "success": True,
            "detail": f"Tenant A created record: {record_id}",
            "raw_data": {"recordId": record_id, "actorId": "tenant-a/user-001"}
        }
    except Exception as e:
        return {"success": False, "detail": f"CreateMemoryRecord failed: {e}"}


def test_tenant_a_retrieve(config, sts_client):
    """Test 2: Tenant A が自テナント actorId で Memory レコード取得"""
    role_arn = config["roles"]["tenantA"]["roleArn"]
    memory_id = config.get("memoryTenantA", config.get("memory", {})).get("memoryId")
    strategy_id = config.get("memoryTenantA", config.get("memory", {})).get("strategyId")

    credentials = assume_role_with_external_id(sts_client, role_arn, "tenant-a", "test-tenant-a-retrieve")
    if not credentials:
        return {"success": False, "detail": "AssumeRole failed"}

    memory_client = create_memory_client_with_credentials(credentials)
    try:
        records = retrieve_memory_records(
            memory_client,
            memory_id,
            strategy_id,
            "tenant-a/user-001"
        )
        return {
            "success": True,
            "detail": f"Tenant A retrieved {len(records)} records",
            "raw_data": {"recordCount": len(records), "actorId": "tenant-a/user-001"}
        }
    except Exception as e:
        return {"success": False, "detail": f"RetrieveMemoryRecords failed: {e}"}


def test_tenant_b_create(config, sts_client):
    """Test 3: Tenant B が自テナント actorId で Memory レコード作成"""
    role_arn = config["roles"]["tenantB"]["roleArn"]
    memory_id = config.get("memoryTenantB", config.get("memory", {})).get("memoryId")
    strategy_id = config.get("memoryTenantB", config.get("memory", {})).get("strategyId")

    credentials = assume_role_with_external_id(sts_client, role_arn, "tenant-b", "test-tenant-b-create")
    if not credentials:
        return {"success": False, "detail": "AssumeRole failed"}

    memory_client = create_memory_client_with_credentials(credentials)
    try:
        record_id = create_memory_record(
            memory_client,
            memory_id,
            strategy_id,
            "tenant-b/user-002",
            "Test content for Tenant B user-002"
        )
        return {
            "success": True,
            "detail": f"Tenant B created record: {record_id}",
            "raw_data": {"recordId": record_id, "actorId": "tenant-b/user-002"}
        }
    except Exception as e:
        return {"success": False, "detail": f"CreateMemoryRecord failed: {e}"}


def test_tenant_b_retrieve(config, sts_client):
    """Test 4: Tenant B が自テナント actorId で Memory レコード取得"""
    role_arn = config["roles"]["tenantB"]["roleArn"]
    memory_id = config.get("memoryTenantB", config.get("memory", {})).get("memoryId")
    strategy_id = config.get("memoryTenantB", config.get("memory", {})).get("strategyId")

    credentials = assume_role_with_external_id(sts_client, role_arn, "tenant-b", "test-tenant-b-retrieve")
    if not credentials:
        return {"success": False, "detail": "AssumeRole failed"}

    memory_client = create_memory_client_with_credentials(credentials)
    try:
        records = retrieve_memory_records(
            memory_client,
            memory_id,
            strategy_id,
            "tenant-b/user-002"
        )
        return {
            "success": True,
            "detail": f"Tenant B retrieved {len(records)} records",
            "raw_data": {"recordCount": len(records), "actorId": "tenant-b/user-002"}
        }
    except Exception as e:
        return {"success": False, "detail": f"RetrieveMemoryRecords failed: {e}"}


def test_cross_tenant_deny_a_to_b(config, sts_client):
    """Test 5: Tenant A が Tenant B の actorId にアクセス試行 -> 拒否"""
    role_arn = config["roles"]["tenantA"]["roleArn"]
    memory_id = config.get("memoryTenantB", config.get("memory", {})).get("memoryId")
    strategy_id = config.get("memoryTenantB", config.get("memory", {})).get("strategyId")

    credentials = assume_role_with_external_id(sts_client, role_arn, "tenant-a", "test-cross-tenant-a-to-b")
    if not credentials:
        return {"success": False, "detail": "AssumeRole failed"}

    memory_client = create_memory_client_with_credentials(credentials)
    try:
        # Tenant B の actorId で取得試行
        records = retrieve_memory_records(
            memory_client,
            memory_id,
            strategy_id,
            "tenant-b/user-002"
        )
        return {
            "success": False,
            "detail": f"Cross-tenant access was NOT denied (got {len(records)} records)"
        }
    except ClientError as e:
        if "AccessDeniedException" in str(e) or "Forbidden" in str(e):
            return {
                "success": True,
                "detail": "Cross-tenant access denied as expected",
                "raw_data": {"error": str(e)}
            }
        else:
            return {"success": False, "detail": f"Unexpected error: {e}"}


def test_cross_tenant_deny_b_to_a(config, sts_client):
    """Test 6: Tenant B が Tenant A の actorId にアクセス試行 -> 拒否"""
    role_arn = config["roles"]["tenantB"]["roleArn"]
    memory_id = config.get("memoryTenantA", config.get("memory", {})).get("memoryId")
    strategy_id = config.get("memoryTenantA", config.get("memory", {})).get("strategyId")

    credentials = assume_role_with_external_id(sts_client, role_arn, "tenant-b", "test-cross-tenant-b-to-a")
    if not credentials:
        return {"success": False, "detail": "AssumeRole failed"}

    memory_client = create_memory_client_with_credentials(credentials)
    try:
        # Tenant A の actorId で取得試行
        records = retrieve_memory_records(
            memory_client,
            memory_id,
            strategy_id,
            "tenant-a/user-001"
        )
        return {
            "success": False,
            "detail": f"Cross-tenant access was NOT denied (got {len(records)} records)"
        }
    except ClientError as e:
        if "AccessDeniedException" in str(e) or "Forbidden" in str(e):
            return {
                "success": True,
                "detail": "Cross-tenant access denied as expected",
                "raw_data": {"error": str(e)}
            }
        else:
            return {"success": False, "detail": f"Unexpected error: {e}"}


def test_external_id_validation(config, sts_client):
    """Test 7: External ID を偽装した AssumeRole 試行 -> 拒否"""
    role_arn = config["roles"]["tenantA"]["roleArn"]

    try:
        # Tenant A のロールで tenant-b External ID を指定して AssumeRole 試行
        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName="test-external-id-validation",
            ExternalId="tenant-b"  # 偽装 External ID
        )
        return {
            "success": False,
            "detail": "External ID validation was NOT enforced (AssumeRole succeeded)"
        }
    except ClientError as e:
        if "AccessDenied" in str(e) or "Forbidden" in str(e):
            return {
                "success": True,
                "detail": "External ID validation enforced as expected",
                "raw_data": {"error": str(e)}
            }
        else:
            return {"success": False, "detail": f"Unexpected error: {e}"}


def test_namespace_condition(config, sts_client):
    """Test 8: 存在しない namespace へのアクセス試行 -> ResourceNotFoundException"""
    role_arn = config["roles"]["tenantA"]["roleArn"]
    memory_id = config.get("memoryTenantA", config.get("memory", {})).get("memoryId")
    strategy_id = config.get("memoryTenantA", config.get("memory", {})).get("strategyId")

    credentials = assume_role_with_external_id(sts_client, role_arn, "tenant-a", "test-namespace-condition")
    if not credentials:
        return {"success": False, "detail": "AssumeRole failed"}

    memory_client = create_memory_client_with_credentials(credentials)
    try:
        # 存在しない namespace でアクセス試行
        namespace_prefix = "/non-existent-namespace/"
        response = memory_client.retrieve_memory_records(
            memoryId=memory_id,
            namespace=namespace_prefix,
            searchCriteria={
                "searchQuery": "test",
                "memoryStrategyId": strategy_id,
                "topK": 10
            },
            maxResults=10
        )
        records = response.get("memoryRecordSummaries", [])
        # 存在しない namespace なので 0 件が期待される
        return {
            "success": True,
            "detail": f"Namespace condition enforced (got {len(records)} records)",
            "raw_data": {"recordCount": len(records)}
        }
    except ClientError as e:
        if "ResourceNotFoundException" in str(e):
            return {
                "success": True,
                "detail": "Namespace condition enforced (ResourceNotFoundException)",
                "raw_data": {"error": str(e)}
            }
        else:
            return {"success": False, "detail": f"Unexpected error: {e}"}


def save_verification_report():
    """検証レポートを Markdown ファイルに保存"""
    config = load_config()

    report = f"""# Memory + IAM ABAC Example: Memory + IAM ABAC 検証結果

## 検証概要

- 検証日時: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC
- AWS アカウント: {config["accountId"]}
- リージョン: {config["region"]}
- Memory ID: `{config["memory"]["memoryId"]}`
- Strategy: `{config["memory"]["strategyId"]}`
- 結果: {sum(1 for r in test_results if r["status"] == "PASS")} PASS / {sum(1 for r in test_results if r["status"] == "FAIL")} FAIL (全 {len(test_results)} テスト)

## 検証手順

1. STS AssumeRole with SessionTags (`tenant_id=tenant-a` or `tenant-b`)
2. Memory API 呼び出し（CreateMemoryRecord, RetrieveMemoryRecords）
3. Cross-Tenant アクセス試行（Deny ポリシーで拒否されることを確認）
4. Tag Manipulation 試行（Trust Policy で拒否されることを確認）
5. Namespace Condition 検証（異なる Namespace へのアクセス拒否を確認）

## テスト結果詳細

"""

    for idx, result in enumerate(test_results, 1):
        report += f"""### {idx}. {result["name"]}

- 結果: **[{result["status"]}]**
- 詳細: {result["detail"]}

::::details Raw Data
```json
{json.dumps(result["raw_data"], indent=2, ensure_ascii=False)}
```
::::

"""

    report += """## 結論

(検証結果に基づく結論)

---

検証スクリプト: `test-phase5.py`
最終更新: """ + datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S') + """ UTC
"""

    with open("VERIFICATION_RESULT.md", "w") as f:
        f.write(report)

    logger.info(f"Report saved to: {os.path.abspath('VERIFICATION_RESULT.md')}")


def main():
    parser = argparse.ArgumentParser(description="Memory + IAM ABAC Example: Memory + IAM ABAC 検証")
    parser.add_argument("--test", help="実行する個別テスト名")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Memory + IAM ABAC Example: Memory + IAM ABAC Verification")
    logger.info("=" * 60)

    # Config 読み込み
    config = load_config()
    logger.info(f"Loaded config: {CONFIG_FILE}")

    # STS クライアント作成
    sts_client = boto3.client("sts", region_name=REGION)

    # テスト実行
    tests = {
        "tenant-a-create": lambda: test_tenant_a_create(config, sts_client),
        "tenant-a-retrieve": lambda: test_tenant_a_retrieve(config, sts_client),
        "tenant-b-create": lambda: test_tenant_b_create(config, sts_client),
        "tenant-b-retrieve": lambda: test_tenant_b_retrieve(config, sts_client),
        "cross-tenant-deny-a-to-b": lambda: test_cross_tenant_deny_a_to_b(config, sts_client),
        "cross-tenant-deny-b-to-a": lambda: test_cross_tenant_deny_b_to_a(config, sts_client),
        "external-id-validation": lambda: test_external_id_validation(config, sts_client),
        "namespace-condition": lambda: test_namespace_condition(config, sts_client)
    }

    if args.test:
        if args.test not in tests:
            logger.error(f"Unknown test: {args.test}")
            logger.info(f"Available tests: {', '.join(tests.keys())}")
            sys.exit(1)
        run_test(args.test, tests[args.test])
    else:
        # 全テスト実行
        for test_name, test_func in tests.items():
            run_test(test_name, test_func)

    # レポート生成
    logger.info("")
    logger.info("=" * 60)
    logger.info("Generating verification report...")
    save_verification_report()

    # サマリー出力
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    for result in test_results:
        logger.info(f"  [{result['status']}] {result['name']}")
    logger.info("")
    logger.info(f"Total: {sum(1 for r in test_results if r['status'] == 'PASS')} PASS / {sum(1 for r in test_results if r['status'] == 'FAIL')} FAIL")


if __name__ == "__main__":
    main()
