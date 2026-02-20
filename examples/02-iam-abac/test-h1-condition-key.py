#!/usr/bin/env python3
"""
H-1: bedrock-agentcore:namespace Condition Key の直接検証

検証内容:
- Condition Key 付き IAM ポリシーで Memory API を呼び出し
- Condition Key が IAM レベルで評価されているかを確認
"""

import boto3
import json
import os
import sys
from datetime import datetime, timezone
from botocore.exceptions import ClientError

REGION = "us-east-1"
CONFIG_FILE = "phase5-config.json"

# テストロール名
TEST_ROLE_WITH_CONDITION = "e2e-h1-test-role-with-condition"
TEST_ROLE_WITHOUT_CONDITION = "e2e-h1-test-role-without-condition"


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Config file not found: {CONFIG_FILE}")
        print("  Run: python3 setup-memory-multi-tenant.py first")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def get_account_id():
    """AWS アカウント ID を取得"""
    sts = boto3.client("sts", region_name=REGION)
    return sts.get_caller_identity()["Account"]


def create_test_role_with_condition(iam_client, account_id, memory_arn):
    """Condition Key 付きテストロールを作成"""
    role_name = TEST_ROLE_WITH_CONDITION

    # Trust Policy
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"sts:ExternalId": "h1-test"}
            }
        }]
    }

    # IAM ポリシー（namespace Condition Key 付き）
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowMemoryAccessWithNamespaceCondition",
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:BatchCreateMemoryRecords",
                "bedrock-agentcore:RetrieveMemoryRecords"
            ],
            "Resource": memory_arn,
            "Condition": {
                "StringLike": {
                    "bedrock-agentcore:namespace": "/tenant-a/*"
                }
            }
        }]
    }

    try:
        # ロール作成
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="H-1 Test: Role with namespace Condition Key"
        )
        print(f"[OK] Created role: {role_name}")

        # ポリシーをアタッチ
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName="MemoryAccessWithCondition",
            PolicyDocument=json.dumps(policy)
        )
        print(f"[OK] Attached policy with namespace Condition Key")

        return f"arn:aws:iam::{account_id}:role/{role_name}"
    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            print(f"[INFO] Role already exists: {role_name}")
            return f"arn:aws:iam::{account_id}:role/{role_name}"
        raise


def create_test_role_without_condition(iam_client, account_id, memory_arn):
    """Condition Key なしテストロールを作成"""
    role_name = TEST_ROLE_WITHOUT_CONDITION

    # Trust Policy
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"sts:ExternalId": "h1-test"}
            }
        }]
    }

    # IAM ポリシー（Condition なし）
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowMemoryAccessWithoutCondition",
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:BatchCreateMemoryRecords",
                "bedrock-agentcore:RetrieveMemoryRecords"
            ],
            "Resource": memory_arn
        }]
    }

    try:
        # ロール作成
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="H-1 Test: Role without namespace Condition Key"
        )
        print(f"[OK] Created role: {role_name}")

        # ポリシーをアタッチ
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName="MemoryAccessWithoutCondition",
            PolicyDocument=json.dumps(policy)
        )
        print(f"[OK] Attached policy without Condition Key")

        return f"arn:aws:iam::{account_id}:role/{role_name}"
    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            print(f"[INFO] Role already exists: {role_name}")
            return f"arn:aws:iam::{account_id}:role/{role_name}"
        raise


def assume_role_with_external_id(sts_client, role_arn, session_name):
    """STS AssumeRole with External ID"""
    response = sts_client.assume_role(
        RoleArn=role_arn,
        RoleSessionName=session_name,
        ExternalId="h1-test"
    )
    return response["Credentials"]


def test_memory_access(credentials, memory_id, strategy_id, namespace):
    """Memory API にアクセスしてテスト"""
    client = boto3.client(
        "bedrock-agentcore",
        region_name=REGION,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"]
    )

    try:
        # requestIdentifier は [a-zA-Z0-9_-]+ のみ許可
        timestamp_str = datetime.now().strftime("%Y%m%d%H%M%S%f")
        response = client.batch_create_memory_records(
            memoryId=memory_id,
            records=[{
                "requestIdentifier": f"h1-test-{timestamp_str}",
                "namespaces": [namespace],
                "content": {"text": f"Test record for namespace {namespace}"},
                "timestamp": datetime.now(timezone.utc),
                "memoryStrategyId": strategy_id
            }]
        )
        return {"success": True, "recordId": response.get("recordIds", ["unknown"])[0]}
    except ClientError as e:
        return {"success": False, "error": str(e)}


def main():
    print("="*80)
    print("H-1: bedrock-agentcore:namespace Condition Key の直接検証")
    print("="*80)

    # 設定読み込み
    config = load_config()
    account_id = get_account_id()

    # Tenant A の Memory 情報を取得
    tenant_a_memory_id = config["memoryTenantA"]["memoryId"]
    tenant_a_strategy_id = config["memoryTenantA"]["strategyId"]
    tenant_a_memory_arn = config["memoryTenantA"]["memoryArn"]

    print(f"\n[INFO] Account ID: {account_id}")
    print(f"[INFO] Tenant A Memory ID: {tenant_a_memory_id}")
    print(f"[INFO] Tenant A Strategy ID: {tenant_a_strategy_id}")

    # IAM / STS クライアント
    iam_client = boto3.client("iam", region_name=REGION)
    sts_client = boto3.client("sts", region_name=REGION)

    # テストロール作成
    print("\n" + "-"*80)
    print("Step 1: テストロールの作成")
    print("-"*80)

    role_with_condition_arn = create_test_role_with_condition(iam_client, account_id, tenant_a_memory_arn)
    role_without_condition_arn = create_test_role_without_condition(iam_client, account_id, tenant_a_memory_arn)

    # IAM ポリシーの伝播待ち
    print("\n[INFO] Waiting 10 seconds for IAM policy propagation...")
    import time
    time.sleep(10)

    # テスト実行
    print("\n" + "-"*80)
    print("Step 2: テスト実行")
    print("-"*80)

    results = []

    # テスト 1-1: Condition Key 付きロール + 一致する namespace (/tenant-a/*)
    print("\n[TEST 1-1] Condition Key 付きロール + 一致する namespace (/tenant-a/user-001/)")
    creds1 = assume_role_with_external_id(sts_client, role_with_condition_arn, "h1-test-1-1")
    result1_1 = test_memory_access(creds1, tenant_a_memory_id, tenant_a_strategy_id, "/tenant-a/user-001/")
    print(f"  結果: {result1_1}")
    results.append(("1-1: With Condition + Match", result1_1))

    # テスト 1-2: Condition Key 付きロール + 不一致の namespace (/tenant-b/*)
    print("\n[TEST 1-2] Condition Key 付きロール + 不一致の namespace (/tenant-b/user-002/)")
    creds2 = assume_role_with_external_id(sts_client, role_with_condition_arn, "h1-test-1-2")
    result1_2 = test_memory_access(creds2, tenant_a_memory_id, tenant_a_strategy_id, "/tenant-b/user-002/")
    print(f"  結果: {result1_2}")
    results.append(("1-2: With Condition + Mismatch", result1_2))

    # テスト 2: Condition Key なしロール + 任意の namespace
    print("\n[TEST 2] Condition Key なしロール + 任意の namespace (/tenant-b/user-002/)")
    creds3 = assume_role_with_external_id(sts_client, role_without_condition_arn, "h1-test-2")
    result2 = test_memory_access(creds3, tenant_a_memory_id, tenant_a_strategy_id, "/tenant-b/user-002/")
    print(f"  結果: {result2}")
    results.append(("2: Without Condition", result2))

    # 結果分析
    print("\n" + "="*80)
    print("検証結果サマリー")
    print("="*80)

    for name, result in results:
        status = "[PASS]" if result["success"] else "[FAIL]"
        print(f"{status} {name}: {result}")

    # 判定
    print("\n" + "="*80)
    print("判定")
    print("="*80)

    if results[0][1]["success"] and results[1][1]["success"] and results[2][1]["success"]:
        print("[結論] Condition Key は IAM レベルで評価されていない")
        print("  - テスト 1-1 (一致): 成功")
        print("  - テスト 1-2 (不一致): 成功（本来は失敗すべき）")
        print("  - テスト 2 (Condition なし): 成功")
        print("\n  → Condition Key を設定しても、不一致の namespace でアクセスが通る。")
        print("  → 'bedrock-agentcore:namespace' Condition Key は API レベルで未サポート。")
    elif results[0][1]["success"] and not results[1][1]["success"] and results[2][1]["success"]:
        print("[結論] Condition Key は IAM レベルで正常に評価されている")
        print("  - テスト 1-1 (一致): 成功")
        print("  - テスト 1-2 (不一致): 失敗（期待通り）")
        print("  - テスト 2 (Condition なし): 成功")
        print("\n  → Condition Key は正常に機能している。")
    else:
        print("[結論] 予期しない結果")
        print("  詳細な分析が必要です。")


if __name__ == "__main__":
    main()
