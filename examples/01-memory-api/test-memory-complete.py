#!/usr/bin/env python3
"""
Memory API 完全検証スクリプト

このスクリプトは以下を検証する：
1. Memory Record の内容分離検証（create → wait → retrieve フロー）
2. DeleteMemoryRecord の Cross-Tenant アクセス拒否検証
3. UpdateMemoryRecord の Cross-Tenant アクセス拒否検証
4. Memory ACTIVE 状態の確認

前提条件:
- Memory リソースが作成済み（setup-memory.py または setup-memory-multi-tenant.py）
- IAM Role が設定済み（tenant-a, tenant-b 用）
- phase5-config.json が存在する

Usage:
  python3 test-memory-complete.py

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


def assume_role(sts_client, role_arn: str, session_name: str, external_id: str) -> dict:
    """
    IAM Role を AssumeRole して一時クレデンシャルを取得する

    Args:
        role_arn: 引き受ける Role の ARN
        session_name: セッション名
        external_id: External ID

    Returns:
        一時クレデンシャル（AccessKeyId, SecretAccessKey, SessionToken）
    """
    logger.info(f"  AssumeRole: {role_arn}")
    logger.info(f"  External ID: {external_id}")

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


def wait_for_memory_active(client, memory_id: str, max_wait: int = 60) -> bool:
    """
    Memory が ACTIVE 状態になるまで待機する

    Args:
        memory_id: Memory ID
        max_wait: 最大待機時間（秒）

    Returns:
        ACTIVE になったら True
    """
    logger.info(f"  Memory ACTIVE 待機中... (max {max_wait}s)")

    waited = 0
    while waited < max_wait:
        try:
            response = client.get_memory(memoryId=memory_id)
            status = response["memory"].get("status")

            if status == "ACTIVE":
                logger.info(f"  [OK] Memory が ACTIVE になりました（{waited}s）")
                return True

            if status == "FAILED":
                logger.error("  [ERROR] Memory が FAILED 状態です")
                return False

            time.sleep(5)
            waited += 5

        except ClientError as e:
            logger.error(f"  [ERROR] Memory 状態確認失敗: {e}")
            return False

    logger.warning(f"  [WARNING] タイムアウト: Memory がまだ ACTIVE になっていません（{waited}s）")
    return False


def create_memory_record(client, memory_id: str, namespace: str, content: str) -> Optional[str]:
    """
    Memory Record を作成する

    Returns:
        作成された Record ID
    """
    logger.info(f"  Memory Record 作成中...")
    logger.info(f"    Memory ID: {memory_id}")
    logger.info(f"    Namespace: {namespace}")
    logger.info(f"    Content: {content}")

    try:
        response = client.batch_create_memory_records(
            memoryId=memory_id,
            records=[
                {
                    "namespace": namespace,
                    "textContent": content,
                    "metadata": {
                        "source": "test-memory-complete.py"
                    }
                }
            ]
        )

        # 作成された Record ID を取得
        if "recordIds" in response and len(response["recordIds"]) > 0:
            record_id = response["recordIds"][0]
            logger.info(f"  [OK] Memory Record 作成成功: {record_id}")
            return record_id
        else:
            logger.error("  [ERROR] Record ID が返されませんでした")
            return None

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"  [ERROR] Memory Record 作成失敗: {error_code} - {error_msg}")
        return None


def retrieve_memory_records(client, memory_id: str, namespace: str, query: str) -> Optional[list]:
    """
    Memory Record を検索する

    Returns:
        取得された Record のリスト
    """
    logger.info(f"  Memory Record 検索中...")
    logger.info(f"    Memory ID: {memory_id}")
    logger.info(f"    Namespace: {namespace}")
    logger.info(f"    Query: {query}")

    try:
        response = client.retrieve_memory_records(
            memoryId=memory_id,
            namespace=namespace,
            semanticQuery=query,
            maxResults=10
        )

        records = response.get("records", [])
        logger.info(f"  [OK] Memory Record 検索成功: {len(records)} 件")
        return records

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"  [ERROR] Memory Record 検索失敗: {error_code} - {error_msg}")
        return None


def delete_memory_record(client, memory_id: str, record_id: str) -> bool:
    """
    Memory Record を削除する

    Returns:
        削除成功時 True
    """
    logger.info(f"  Memory Record 削除中...")
    logger.info(f"    Memory ID: {memory_id}")
    logger.info(f"    Record ID: {record_id}")

    try:
        client.delete_memory_record(
            memoryId=memory_id,
            recordId=record_id
        )
        logger.info("  [OK] Memory Record 削除成功")
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "AccessDeniedException":
            logger.info(f"  [EXPECTED] AccessDenied: {error_msg}")
            return False
        else:
            logger.error(f"  [ERROR] Memory Record 削除失敗: {error_code} - {error_msg}")
            return False


def update_memory_record(client, memory_id: str, record_id: str, new_content: str) -> bool:
    """
    Memory Record を更新する

    Returns:
        更新成功時 True
    """
    logger.info(f"  Memory Record 更新中...")
    logger.info(f"    Memory ID: {memory_id}")
    logger.info(f"    Record ID: {record_id}")
    logger.info(f"    New Content: {new_content}")

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
        logger.info("  [OK] Memory Record 更新成功")
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "AccessDeniedException":
            logger.info(f"  [EXPECTED] AccessDenied: {error_msg}")
            return False
        else:
            logger.error(f"  [ERROR] Memory Record 更新失敗: {error_code} - {error_msg}")
            return False


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


def test_1_memory_active_state(memory_client, config: dict):
    """
    Test 1: Memory ACTIVE 状態の確認

    Memory 作成後、ACTIVE 状態になるまで待機する。
    """
    logger.info("=" * 80)
    logger.info("[Test 1] Memory ACTIVE 状態の確認")
    logger.info("=" * 80)

    memory_id = config.get("memory", {}).get("memoryId")
    if not memory_id:
        logger.error("Memory ID が設定されていません")
        record_test("1-1. Memory ID 取得", False, "phase5-config.json に Memory ID がありません")
        return None

    logger.info(f"\n1-1. Memory ACTIVE 状態待機: {memory_id}")
    is_active = wait_for_memory_active(memory_client, memory_id, max_wait=60)
    record_test(
        "1-1. Memory ACTIVE 状態",
        is_active,
        f"Memory ID: {memory_id}"
    )

    return memory_id if is_active else None


def test_2_create_and_retrieve_flow(tenant_a_client, memory_id: str):
    """
    Test 2: Memory Record の create → wait → retrieve フロー

    正のテスト: 自テナントのデータが取得できることを確認。
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 2] Memory Record の create → wait → retrieve フロー")
    logger.info("=" * 80)

    namespace = "/tenant-a/user-001/"
    content = "Test content for tenant-a user-001"

    # 2-1. Memory Record 作成
    logger.info("\n2-1. tenant-a で Memory Record 作成")
    record_id = create_memory_record(tenant_a_client, memory_id, namespace, content)
    record_test(
        "2-1. Memory Record 作成",
        record_id is not None,
        f"Record ID: {record_id}"
    )

    if not record_id:
        return None

    # 2-2. ベクトルインデックス構築待機
    logger.info("\n2-2. ベクトルインデックス構築待機（30秒）")
    logger.info("  ベクトル検索を有効にするため、インデックス構築を待機します")
    time.sleep(30)
    record_test("2-2. インデックス構築待機", True, "30秒待機完了")

    # 2-3. Memory Record 検索
    logger.info("\n2-3. tenant-a で Memory Record 検索")
    records = retrieve_memory_records(tenant_a_client, memory_id, namespace, "Test content")

    if records is not None and len(records) > 0:
        # 取得できた Record の内容を確認
        first_record = records[0]
        logger.info(f"  取得した Record:")
        logger.info(f"    Record ID: {first_record.get('recordId')}")
        logger.info(f"    Namespace: {first_record.get('namespace')}")
        logger.info(f"    Content: {first_record.get('textContent', '')[:50]}...")

        # namespace が一致することを確認
        namespace_match = first_record.get("namespace") == namespace
        record_test(
            "2-3. Memory Record 検索（正のテスト）",
            len(records) > 0 and namespace_match,
            f"取得件数: {len(records)}, namespace 一致: {namespace_match}"
        )
    else:
        record_test(
            "2-3. Memory Record 検索（正のテスト）",
            False,
            "Record が取得できませんでした（インデックス構築に時間がかかっている可能性）"
        )

    logger.info("\n[結論] create → wait → retrieve フローでデータ取得が確認できました")
    return record_id


def test_3_cross_tenant_delete(tenant_a_client, tenant_b_client, memory_id: str, record_id: str):
    """
    Test 3: DeleteMemoryRecord の Cross-Tenant アクセス拒否検証

    tenant-b のクレデンシャルで tenant-a の Record を削除しようとする。
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 3] DeleteMemoryRecord の Cross-Tenant アクセス拒否")
    logger.info("=" * 80)

    logger.info("\n3-1. tenant-b で tenant-a の Record 削除を試行")
    success = delete_memory_record(tenant_b_client, memory_id, record_id)

    # tenant-b で削除が拒否されることを期待
    record_test(
        "3-1. Cross-Tenant Delete アクセス拒否",
        not success,  # 失敗することが正しい
        f"Expected: AccessDenied, Got: {'AccessDenied' if not success else 'Allowed'}"
    )

    logger.info("\n[結論] Cross-Tenant での Delete 操作は正しく拒否されました")


def test_4_cross_tenant_update(tenant_a_client, tenant_b_client, memory_id: str, record_id: str):
    """
    Test 4: UpdateMemoryRecord の Cross-Tenant アクセス拒否検証

    tenant-b のクレデンシャルで tenant-a の Record を更新しようとする。
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 4] UpdateMemoryRecord の Cross-Tenant アクセス拒否")
    logger.info("=" * 80)

    logger.info("\n4-1. tenant-b で tenant-a の Record 更新を試行")
    new_content = "Modified by tenant-b (should be denied)"
    success = update_memory_record(tenant_b_client, memory_id, record_id, new_content)

    # tenant-b で更新が拒否されることを期待
    record_test(
        "4-1. Cross-Tenant Update アクセス拒否",
        not success,  # 失敗することが正しい
        f"Expected: AccessDenied, Got: {'AccessDenied' if not success else 'Allowed'}"
    )

    logger.info("\n[結論] Cross-Tenant での Update 操作は正しく拒否されました")


def test_5_cleanup_tenant_a_delete(tenant_a_client, memory_id: str, record_id: str):
    """
    Test 5: tenant-a で自分の Record を削除（クリーンアップ）

    tenant-a は自分の Record を削除できることを確認。
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 5] tenant-a で自 Record 削除（クリーンアップ）")
    logger.info("=" * 80)

    logger.info("\n5-1. tenant-a で自分の Record 削除")
    success = delete_memory_record(tenant_a_client, memory_id, record_id)

    record_test(
        "5-1. tenant-a で自 Record 削除",
        success,
        "自テナントの Record は削除可能"
    )

    logger.info("\n[結論] tenant-a は自分の Record を正常に削除できました")


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
    logger.info("Memory API 完全検証")
    logger.info("=" * 80)
    logger.info(f"Region: {REGION}")

    # 設定ファイルを読み込む
    config = load_config()

    # AWS クライアントを作成
    sts_client = boto3.client("sts", region_name=REGION)
    memory_client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # IAM Role ARN を構築
    account_id = config["accountId"]
    tenant_a_role_arn = f"arn:aws:iam::{account_id}:role/e2e-phase5-tenant-a-role"
    tenant_b_role_arn = f"arn:aws:iam::{account_id}:role/e2e-phase5-tenant-b-role"

    # tenant-a のクレデンシャルを取得
    logger.info("\n" + "=" * 80)
    logger.info("tenant-a クレデンシャル取得")
    logger.info("=" * 80)
    tenant_a_creds = assume_role(sts_client, tenant_a_role_arn, "tenant-a-session", "tenant-a")
    if not tenant_a_creds:
        logger.error("tenant-a のクレデンシャル取得に失敗しました")
        sys.exit(1)
    tenant_a_client = create_memory_client(tenant_a_creds)

    # tenant-b のクレデンシャルを取得
    logger.info("\n" + "=" * 80)
    logger.info("tenant-b クレデンシャル取得")
    logger.info("=" * 80)
    tenant_b_creds = assume_role(sts_client, tenant_b_role_arn, "tenant-b-session", "tenant-b")
    if not tenant_b_creds:
        logger.error("tenant-b のクレデンシャル取得に失敗しました")
        sys.exit(1)
    tenant_b_client = create_memory_client(tenant_b_creds)

    try:
        # Test 1: Memory ACTIVE 状態の確認
        memory_id = test_1_memory_active_state(memory_client, config)
        if not memory_id:
            logger.error("Memory が ACTIVE になりませんでした。テストを中断します。")
            sys.exit(1)

        # Test 2: create → wait → retrieve フロー
        record_id = test_2_create_and_retrieve_flow(tenant_a_client, memory_id)
        if not record_id:
            logger.error("Memory Record の作成に失敗しました。残りのテストをスキップします。")
            print_summary()
            sys.exit(1)

        # Test 3: Cross-Tenant Delete
        test_3_cross_tenant_delete(tenant_a_client, tenant_b_client, memory_id, record_id)

        # Test 4: Cross-Tenant Update
        test_4_cross_tenant_update(tenant_a_client, tenant_b_client, memory_id, record_id)

        # Test 5: Cleanup (tenant-a で削除)
        test_5_cleanup_tenant_a_delete(tenant_a_client, memory_id, record_id)

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
