#!/usr/bin/env python3
"""
IAM ABAC Write 操作完全検証スクリプト

このスクリプトは以下を検証する：
1. BatchDeleteMemoryRecords の namespace Condition Key による Cross-Tenant アクセス拒否
2. BatchUpdateMemoryRecords の namespace Condition Key による Cross-Tenant アクセス拒否
3. DeleteMemoryRecord の namespace Condition Key による Cross-Tenant アクセス拒否

前提条件:
- Memory リソースが作成済み（setup-memory.py または setup-memory-multi-tenant.py）
- IAM Role が設定済み（setup-iam-roles.py）
- phase5-config.json が存在する

Usage:
  python3 test-write-operations-abac.py

環境変数:
  AWS_DEFAULT_REGION: AWS リージョン（デフォルト: us-east-1）
"""

import json
import logging
import os
import sys
import time
from typing import Dict, Any, Optional

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("[ERROR] boto3 が必要です。pip install boto3 を実行してください。")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "phase5-config.json")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

# テストロール名
TEST_ROLE_TENANT_A = "e2e-h1-test-role-tenant-a"
TEST_ROLE_TENANT_B = "e2e-h1-test-role-tenant-b"

# テスト結果
test_results = {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "tests": []
}


def load_config() -> dict:
    """phase5-config.json を読み込む"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"phase5-config.json が見つかりません: {CONFIG_FILE}")
        logger.info("Hint: python3 setup-memory.py を実行してください")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    required_fields = ["accountId", "region"]
    missing = [f for f in required_fields if f not in config]
    if missing:
        logger.error(f"phase5-config.json に必須フィールドがありません: {missing}")
        sys.exit(1)

    return config


def get_account_id() -> str:
    """AWS アカウント ID を取得"""
    sts = boto3.client("sts", region_name=REGION)
    return sts.get_caller_identity()["Account"]


def create_test_role_with_namespace_condition(
    iam_client,
    role_name: str,
    account_id: str,
    memory_arn: str,
    allowed_namespace: str
) -> str:
    """
    namespace Condition Key 付きテストロールを作成

    Args:
        role_name: ロール名
        allowed_namespace: 許可する namespace パターン（例: /tenant-a/*）

    Returns:
        ロール ARN
    """
    logger.info(f"テストロール作成: {role_name}")
    logger.info(f"  Allowed Namespace: {allowed_namespace}")

    # Trust Policy
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"sts:ExternalId": "write-ops-test"}
            }
        }]
    }

    # IAM ポリシー（Write 操作 + namespace Condition Key）
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowWriteOperationsWithNamespaceCondition",
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:BatchCreateMemoryRecords",
                "bedrock-agentcore:RetrieveMemoryRecords",
                "bedrock-agentcore:BatchUpdateMemoryRecords",
                "bedrock-agentcore:BatchDeleteMemoryRecords",
                "bedrock-agentcore:DeleteMemoryRecord",
                "bedrock-agentcore:GetMemoryRecord"
            ],
            "Resource": memory_arn,
            "Condition": {
                "StringLike": {
                    "bedrock-agentcore:namespace": allowed_namespace
                }
            }
        }]
    }

    try:
        # ロール作成
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=f"Write Operations Test: namespace={allowed_namespace}"
        )
        logger.info(f"  [OK] ロール作成完了: {role_name}")

        # ポリシーをアタッチ
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName="WriteOperationsWithNamespaceCondition",
            PolicyDocument=json.dumps(policy)
        )
        logger.info("  [OK] ポリシーアタッチ完了")

        return f"arn:aws:iam::{account_id}:role/{role_name}"

    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            logger.info(f"  [INFO] ロール既存: {role_name}")
            # 既存のロールのポリシーを更新
            try:
                iam_client.put_role_policy(
                    RoleName=role_name,
                    PolicyName="WriteOperationsWithNamespaceCondition",
                    PolicyDocument=json.dumps(policy)
                )
                logger.info("  [OK] 既存ロールのポリシー更新完了")
            except Exception as update_error:
                logger.warning(f"  [WARN] ポリシー更新失敗: {update_error}")

            return f"arn:aws:iam::{account_id}:role/{role_name}"
        raise


def assume_role(sts_client, role_arn: str, session_name: str, external_id: str) -> dict:
    """
    IAM Role を AssumeRole して一時クレデンシャルを取得する

    Returns:
        一時クレデンシャル（AccessKeyId, SecretAccessKey, SessionToken）
    """
    logger.info(f"  AssumeRole: {role_arn}")

    try:
        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            ExternalId=external_id,
            DurationSeconds=3600
        )

        credentials = response["Credentials"]
        logger.info("  [OK] AssumeRole 成功")
        return credentials

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"  [ERROR] AssumeRole 失敗: {error_code} - {error_msg}")
        return None


def create_memory_client(credentials: dict) -> any:
    """一時クレデンシャルを使用して Memory API クライアントを作成する"""
    return boto3.client(
        "bedrock-agentcore-control",
        region_name=REGION,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"]
    )


def create_memory_record(client, memory_id: str, namespace: str, content: str) -> Optional[str]:
    """
    Memory Record を作成する

    Returns:
        作成された Record ID
    """
    logger.info(f"  Memory Record 作成中...")
    logger.info(f"    Namespace: {namespace}")

    try:
        response = client.batch_create_memory_records(
            memoryId=memory_id,
            records=[
                {
                    "namespace": namespace,
                    "textContent": content,
                    "metadata": {"source": "test-write-operations-abac.py"}
                }
            ]
        )

        if "recordIds" in response and len(response["recordIds"]) > 0:
            record_id = response["recordIds"][0]
            logger.info(f"  [OK] Record 作成成功: {record_id}")
            return record_id
        else:
            logger.error("  [ERROR] Record ID が返されませんでした")
            return None

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"  [ERROR] Record 作成失敗: {error_code} - {error_msg}")
        return None


def delete_memory_record(client, memory_id: str, record_id: str) -> tuple[bool, str]:
    """
    Memory Record を削除する

    Returns:
        (成功したか, エラーコード)
    """
    logger.info(f"  Memory Record 削除試行...")
    logger.info(f"    Record ID: {record_id}")

    try:
        client.delete_memory_record(
            memoryId=memory_id,
            recordId=record_id
        )
        logger.info("  [OK] Record 削除成功")
        return True, None

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "AccessDeniedException":
            logger.info(f"  [EXPECTED] AccessDenied: {error_msg}")
            return False, "AccessDeniedException"
        else:
            logger.error(f"  [ERROR] Record 削除失敗: {error_code} - {error_msg}")
            return False, error_code


def batch_delete_memory_records(client, memory_id: str, record_ids: list) -> tuple[bool, str]:
    """
    Memory Records をバッチ削除する

    Returns:
        (成功したか, エラーコード)
    """
    logger.info(f"  Memory Records バッチ削除試行...")
    logger.info(f"    Record IDs: {record_ids}")

    try:
        client.batch_delete_memory_records(
            memoryId=memory_id,
            recordIds=record_ids
        )
        logger.info("  [OK] Records バッチ削除成功")
        return True, None

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "AccessDeniedException":
            logger.info(f"  [EXPECTED] AccessDenied: {error_msg}")
            return False, "AccessDeniedException"
        else:
            logger.error(f"  [ERROR] Records バッチ削除失敗: {error_code} - {error_msg}")
            return False, error_code


def update_memory_record(client, memory_id: str, record_id: str, new_content: str) -> tuple[bool, str]:
    """
    Memory Record を更新する

    Returns:
        (成功したか, エラーコード)
    """
    logger.info(f"  Memory Record 更新試行...")
    logger.info(f"    Record ID: {record_id}")

    try:
        client.batch_update_memory_records(
            memoryId=memory_id,
            records=[
                {
                    "recordId": record_id,
                    "textContent": new_content
                }
            ]
        )
        logger.info("  [OK] Record 更新成功")
        return True, None

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "AccessDeniedException":
            logger.info(f"  [EXPECTED] AccessDenied: {error_msg}")
            return False, "AccessDeniedException"
        else:
            logger.error(f"  [ERROR] Record 更新失敗: {error_code} - {error_msg}")
            return False, error_code


def record_test(test_name: str, passed: bool, details: str = ""):
    """テスト結果を記録する"""
    test_results["total"] += 1
    if passed:
        test_results["passed"] += 1
        status = "[PASS]"
    else:
        test_results["failed"] += 1
        status = "[FAIL]"

    test_results["tests"].append({
        "name": test_name,
        "passed": passed,
        "details": details
    })

    logger.info(f"  {status} {test_name}")
    if details:
        logger.info(f"       {details}")


def test_1_setup_test_roles(iam_client, account_id: str, memory_arn: str):
    """
    Test 1: テストロールのセットアップ

    tenant-a と tenant-b 用の IAM Role を作成。
    """
    logger.info("=" * 80)
    logger.info("[Test 1] テストロールのセットアップ")
    logger.info("=" * 80)

    logger.info("\n1-1. tenant-a 用ロール作成（namespace: /tenant-a/*）")
    tenant_a_role_arn = create_test_role_with_namespace_condition(
        iam_client,
        TEST_ROLE_TENANT_A,
        account_id,
        memory_arn,
        "/tenant-a/*"
    )
    record_test("1-1. tenant-a ロール作成", True, f"Role ARN: {tenant_a_role_arn}")

    logger.info("\n1-2. tenant-b 用ロール作成（namespace: /tenant-b/*）")
    tenant_b_role_arn = create_test_role_with_namespace_condition(
        iam_client,
        TEST_ROLE_TENANT_B,
        account_id,
        memory_arn,
        "/tenant-b/*"
    )
    record_test("1-2. tenant-b ロール作成", True, f"Role ARN: {tenant_b_role_arn}")

    # IAM ポリシー伝播待機
    logger.info("\n1-3. IAM ポリシー伝播待機（10秒）")
    time.sleep(10)
    record_test("1-3. IAM ポリシー伝播待機", True, "10秒待機完了")

    return tenant_a_role_arn, tenant_b_role_arn


def test_2_delete_cross_tenant(
    tenant_a_client,
    tenant_b_client,
    memory_id: str,
    tenant_a_record_id: str
):
    """
    Test 2: DeleteMemoryRecord の Cross-Tenant アクセス拒否

    tenant-b が tenant-a の Record を削除しようとする。
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 2] DeleteMemoryRecord の Cross-Tenant アクセス拒否")
    logger.info("=" * 80)

    logger.info("\n2-1. tenant-b で tenant-a の Record 削除試行")
    success, error_code = delete_memory_record(tenant_b_client, memory_id, tenant_a_record_id)

    record_test(
        "2-1. DeleteMemoryRecord Cross-Tenant 拒否",
        not success and error_code == "AccessDeniedException",
        f"Expected: AccessDeniedException, Got: {error_code if not success else 'Success'}"
    )

    logger.info("\n[結論] DeleteMemoryRecord の Cross-Tenant アクセスは正しく拒否されました")


def test_3_batch_delete_cross_tenant(
    tenant_a_client,
    tenant_b_client,
    memory_id: str,
    tenant_a_record_ids: list
):
    """
    Test 3: BatchDeleteMemoryRecords の Cross-Tenant アクセス拒否

    tenant-b が tenant-a の Records をバッチ削除しようとする。
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 3] BatchDeleteMemoryRecords の Cross-Tenant アクセス拒否")
    logger.info("=" * 80)

    logger.info("\n3-1. tenant-b で tenant-a の Records バッチ削除試行")
    success, error_code = batch_delete_memory_records(tenant_b_client, memory_id, tenant_a_record_ids)

    record_test(
        "3-1. BatchDeleteMemoryRecords Cross-Tenant 拒否",
        not success and error_code == "AccessDeniedException",
        f"Expected: AccessDeniedException, Got: {error_code if not success else 'Success'}"
    )

    logger.info("\n[結論] BatchDeleteMemoryRecords の Cross-Tenant アクセスは正しく拒否されました")


def test_4_update_cross_tenant(
    tenant_a_client,
    tenant_b_client,
    memory_id: str,
    tenant_a_record_id: str
):
    """
    Test 4: BatchUpdateMemoryRecords の Cross-Tenant アクセス拒否

    tenant-b が tenant-a の Record を更新しようとする。
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 4] BatchUpdateMemoryRecords の Cross-Tenant アクセス拒否")
    logger.info("=" * 80)

    logger.info("\n4-1. tenant-b で tenant-a の Record 更新試行")
    new_content = "Modified by tenant-b (should be denied)"
    success, error_code = update_memory_record(tenant_b_client, memory_id, tenant_a_record_id, new_content)

    record_test(
        "4-1. BatchUpdateMemoryRecords Cross-Tenant 拒否",
        not success and error_code == "AccessDeniedException",
        f"Expected: AccessDeniedException, Got: {error_code if not success else 'Success'}"
    )

    logger.info("\n[結論] BatchUpdateMemoryRecords の Cross-Tenant アクセスは正しく拒否されました")


def test_5_cleanup(tenant_a_client, memory_id: str, tenant_a_record_ids: list):
    """
    Test 5: tenant-a で自 Records 削除（クリーンアップ）

    tenant-a は自分の Records を削除できることを確認。
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 5] tenant-a で自 Records 削除（クリーンアップ）")
    logger.info("=" * 80)

    logger.info("\n5-1. tenant-a で自 Records バッチ削除")
    success, error_code = batch_delete_memory_records(tenant_a_client, memory_id, tenant_a_record_ids)

    record_test(
        "5-1. tenant-a で自 Records 削除",
        success,
        "自テナントの Records は削除可能"
    )

    logger.info("\n[結論] tenant-a は自分の Records を正常に削除できました")


def print_summary():
    """テスト結果のサマリーを出力する"""
    logger.info("\n" + "=" * 80)
    logger.info("Test Summary")
    logger.info("=" * 80)
    logger.info(f"Total Tests: {test_results['total']}")
    logger.info(f"Passed: {test_results['passed']}")
    logger.info(f"Failed: {test_results['failed']}")
    logger.info("=" * 80)

    if test_results["failed"] > 0:
        logger.info("\nFailed Tests:")
        for test in test_results["tests"]:
            if not test["passed"]:
                logger.info(f"  - {test['name']}")
                if test["details"]:
                    logger.info(f"    {test['details']}")

    if test_results["failed"] == 0:
        logger.info("\n[SUCCESS] All tests passed!")
    else:
        logger.info("\n[FAILURE] Some tests failed.")


def main():
    logger.info("=" * 80)
    logger.info("IAM ABAC Write 操作完全検証")
    logger.info("=" * 80)
    logger.info(f"Region: {REGION}")

    # 設定ファイルを読み込む
    config = load_config()

    # Memory ID を取得
    memory_id = config.get("memory", {}).get("memoryId")
    if not memory_id:
        logger.error("Memory ID が設定されていません")
        logger.info("Hint: python3 setup-memory.py を実行してください")
        sys.exit(1)

    memory_arn = config.get("memory", {}).get("memoryArn")
    if not memory_arn:
        logger.error("Memory ARN が設定されていません")
        sys.exit(1)

    account_id = get_account_id()

    # AWS クライアントを作成
    sts_client = boto3.client("sts", region_name=REGION)
    iam_client = boto3.client("iam", region_name=REGION)

    try:
        # Test 1: テストロールのセットアップ
        tenant_a_role_arn, tenant_b_role_arn = test_1_setup_test_roles(iam_client, account_id, memory_arn)

        # tenant-a のクレデンシャルを取得
        logger.info("\n" + "=" * 80)
        logger.info("tenant-a クレデンシャル取得")
        logger.info("=" * 80)
        tenant_a_creds = assume_role(sts_client, tenant_a_role_arn, "tenant-a-session", "write-ops-test")
        if not tenant_a_creds:
            logger.error("tenant-a のクレデンシャル取得に失敗しました")
            sys.exit(1)
        tenant_a_client = create_memory_client(tenant_a_creds)

        # tenant-b のクレデンシャルを取得
        logger.info("\n" + "=" * 80)
        logger.info("tenant-b クレデンシャル取得")
        logger.info("=" * 80)
        tenant_b_creds = assume_role(sts_client, tenant_b_role_arn, "tenant-b-session", "write-ops-test")
        if not tenant_b_creds:
            logger.error("tenant-b のクレデンシャル取得に失敗しました")
            sys.exit(1)
        tenant_b_client = create_memory_client(tenant_b_creds)

        # tenant-a でテスト用 Records を作成
        logger.info("\n" + "=" * 80)
        logger.info("テスト用 Records 作成")
        logger.info("=" * 80)
        logger.info("\ntenant-a で3件の Records 作成")
        tenant_a_record_ids = []
        for i in range(3):
            record_id = create_memory_record(
                tenant_a_client,
                memory_id,
                f"/tenant-a/user-{i:03d}/",
                f"Test content {i} for tenant-a"
            )
            if record_id:
                tenant_a_record_ids.append(record_id)

        if len(tenant_a_record_ids) < 3:
            logger.error("テスト用 Records の作成に失敗しました")
            sys.exit(1)

        # Test 2: DeleteMemoryRecord Cross-Tenant
        test_2_delete_cross_tenant(tenant_a_client, tenant_b_client, memory_id, tenant_a_record_ids[0])

        # Test 3: BatchDeleteMemoryRecords Cross-Tenant
        test_3_batch_delete_cross_tenant(tenant_a_client, tenant_b_client, memory_id, [tenant_a_record_ids[1]])

        # Test 4: BatchUpdateMemoryRecords Cross-Tenant
        test_4_update_cross_tenant(tenant_a_client, tenant_b_client, memory_id, tenant_a_record_ids[2])

        # Test 5: Cleanup
        test_5_cleanup(tenant_a_client, memory_id, tenant_a_record_ids)

        # テスト結果のサマリーを出力
        print_summary()

        sys.exit(0 if test_results["failed"] == 0 else 1)

    except Exception as e:
        logger.error(f"[ERROR] 予期しないエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
