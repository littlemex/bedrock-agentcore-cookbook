#!/usr/bin/env python3
"""
bedrock-agentcore:actorId Condition Key の直接検証

検証内容:
- Condition Key 付き IAM ポリシーで Memory API を呼び出し
- bedrock-agentcore:actorId が IAM レベルで評価されているかを確認

テスト方針:
- namespace Condition Key の検証（test-h1-condition-key.py）と同じアプローチ
- actorId Condition Key を IAM ポリシーに設定し、
  一致/不一致の actorId で API 呼び出しを試行
"""

import boto3
import json
import os
import sys
import time
from datetime import datetime, timezone
from botocore.exceptions import ClientError

REGION = "us-east-1"

# 設定ファイルのパス（05-end-to-end から読み込み）
CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "05-end-to-end", "phase5-config.json"
)

# テストロール名
TEST_ROLE_ACTORID_CONDITION = "e2e-actorid-test-role-with-condition"
TEST_ROLE_ACTORID_NO_CONDITION = "e2e-actorid-test-role-without-condition"

# テスト用 actorId
ALLOWED_ACTOR_ID = "actor-alice"
DENIED_ACTOR_ID = "actor-bob"


def load_config():
    """設定ファイルを読み込み"""
    config_path = os.path.normpath(CONFIG_FILE)
    if not os.path.exists(config_path):
        print(f"[ERROR] Config file not found: {config_path}")
        print("  Run: cd ../05-end-to-end && python3 setup-memory.py first")
        sys.exit(1)

    with open(config_path, "r") as f:
        return json.load(f)


def get_account_id():
    """AWS Account ID を取得"""
    sts = boto3.client("sts", region_name=REGION)
    return sts.get_caller_identity()["Account"]


def create_test_role_with_actorid_condition(iam_client, account_id, memory_arn):
    """actorId Condition Key 付きテストロールを作成"""
    role_name = TEST_ROLE_ACTORID_CONDITION

    # Trust Policy
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"sts:ExternalId": "actorid-test"}
            }
        }]
    }

    # IAM Policy（actorId Condition Key 付き）
    # actorId が ALLOWED_ACTOR_ID に一致する場合のみ許可
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowMemoryAccessWithActorIdCondition",
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:BatchCreateMemoryRecords",
                "bedrock-agentcore:RetrieveMemoryRecords",
                "bedrock-agentcore:ListMemoryRecords",
                "bedrock-agentcore:ListActors"
            ],
            "Resource": memory_arn,
            "Condition": {
                "StringEquals": {
                    "bedrock-agentcore:actorId": ALLOWED_ACTOR_ID
                }
            }
        }]
    }

    try:
        # ロール作成
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="actorId Condition Key Test: Role with actorId Condition"
        )
        print(f"[OK] Created role: {role_name}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            print(f"[INFO] Role already exists: {role_name}")
            # Trust Policy を更新
            iam_client.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=json.dumps(trust_policy)
            )
            print(f"[OK] Updated trust policy for: {role_name}")
        else:
            raise

    # Inline Policy をアタッチ/更新
    iam_client.put_role_policy(
        RoleName=role_name,
        PolicyName="MemoryAccessWithActorIdCondition",
        PolicyDocument=json.dumps(policy)
    )
    print(f"[OK] Attached policy with actorId Condition Key")
    print(f"  Allowed actorId: {ALLOWED_ACTOR_ID}")

    return f"arn:aws:iam::{account_id}:role/{role_name}"


def create_test_role_without_condition(iam_client, account_id, memory_arn):
    """Condition Key なしテストロールを作成"""
    role_name = TEST_ROLE_ACTORID_NO_CONDITION

    # Trust Policy
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"sts:ExternalId": "actorid-test"}
            }
        }]
    }

    # IAM Policy（Condition なし: 全アクセス許可）
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowMemoryAccessWithoutCondition",
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:BatchCreateMemoryRecords",
                "bedrock-agentcore:RetrieveMemoryRecords",
                "bedrock-agentcore:ListMemoryRecords",
                "bedrock-agentcore:ListActors"
            ],
            "Resource": memory_arn
        }]
    }

    try:
        # ロール作成
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="actorId Condition Key Test: Role without Condition"
        )
        print(f"[OK] Created role: {role_name}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            print(f"[INFO] Role already exists: {role_name}")
            # Trust Policy を更新
            iam_client.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=json.dumps(trust_policy)
            )
            print(f"[OK] Updated trust policy for: {role_name}")
        else:
            raise

    # Inline Policy をアタッチ/更新
    iam_client.put_role_policy(
        RoleName=role_name,
        PolicyName="MemoryAccessWithoutCondition",
        PolicyDocument=json.dumps(policy)
    )
    print(f"[OK] Attached policy without Condition Key")

    return f"arn:aws:iam::{account_id}:role/{role_name}"


def assume_role(sts_client, role_arn, session_name):
    """STS AssumeRole with External ID"""
    response = sts_client.assume_role(
        RoleArn=role_arn,
        RoleSessionName=session_name,
        ExternalId="actorid-test"
    )
    return response["Credentials"]


def test_batch_create_with_namespace(credentials, memory_id, strategy_id, actor_id):
    """
    BatchCreateMemoryRecords で actorId を namespace に含めてテスト。
    actorId Condition Key が namespace 内の actorId を参照するか検証。
    """
    client = boto3.client(
        "bedrock-agentcore",
        region_name=REGION,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"]
    )

    try:
        # namespace に actorId を含める
        namespace = f"/{actor_id}/"
        timestamp_str = datetime.now().strftime("%Y%m%d%H%M%S%f")
        request_id = f"actorid-test-{actor_id.replace('/', '-')}-{timestamp_str}"

        response = client.batch_create_memory_records(
            memoryId=memory_id,
            records=[{
                "requestIdentifier": request_id,
                "namespaces": [namespace],
                "content": {"text": f"Test record for actorId={actor_id}"},
                "timestamp": datetime.now(timezone.utc),
                "memoryStrategyId": strategy_id
            }]
        )

        if response.get("successfulRecords"):
            record = response["successfulRecords"][0]
            return {
                "success": True,
                "recordId": record.get("memoryRecordId", "unknown"),
                "api": "BatchCreateMemoryRecords"
            }
        elif response.get("failedRecords"):
            return {
                "success": False,
                "error": str(response["failedRecords"]),
                "api": "BatchCreateMemoryRecords"
            }
        else:
            return {
                "success": True,
                "recordId": "unknown",
                "api": "BatchCreateMemoryRecords"
            }
    except ClientError as e:
        error_code = e.response['Error']['Code']
        return {
            "success": False,
            "error": str(e),
            "errorCode": error_code,
            "api": "BatchCreateMemoryRecords"
        }


def test_retrieve_records(credentials, memory_id, strategy_id, actor_id):
    """RetrieveMemoryRecords でテスト"""
    client = boto3.client(
        "bedrock-agentcore",
        region_name=REGION,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"]
    )

    try:
        namespace = f"/{actor_id}/"
        response = client.retrieve_memory_records(
            memoryId=memory_id,
            namespace=namespace,
            searchCriteria={
                "searchQuery": "test",
                "memoryStrategyId": strategy_id,
                "topK": 10
            },
            maxResults=10
        )
        records = response.get("memoryRecordSummaries", [])
        return {
            "success": True,
            "recordCount": len(records),
            "api": "RetrieveMemoryRecords"
        }
    except ClientError as e:
        error_code = e.response['Error']['Code']
        return {
            "success": False,
            "error": str(e),
            "errorCode": error_code,
            "api": "RetrieveMemoryRecords"
        }


def test_list_actors(credentials, memory_id):
    """ListActors でテスト（actorId Condition が ListActors にも影響するか）"""
    client = boto3.client(
        "bedrock-agentcore",
        region_name=REGION,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"]
    )

    try:
        response = client.list_actors(
            memoryId=memory_id,
            maxResults=10
        )
        actors = response.get("actorSummaries", [])
        return {
            "success": True,
            "actorCount": len(actors),
            "actors": [a.get("actorId") for a in actors],
            "api": "ListActors"
        }
    except ClientError as e:
        error_code = e.response['Error']['Code']
        return {
            "success": False,
            "error": str(e),
            "errorCode": error_code,
            "api": "ListActors"
        }


def cleanup_roles(iam_client):
    """テストロールをクリーンアップ"""
    for role_name in [TEST_ROLE_ACTORID_CONDITION, TEST_ROLE_ACTORID_NO_CONDITION]:
        try:
            # Inline Policy を削除
            policies = iam_client.list_role_policies(RoleName=role_name)
            for policy_name in policies.get("PolicyNames", []):
                iam_client.delete_role_policy(
                    RoleName=role_name,
                    PolicyName=policy_name
                )
                print(f"[OK] Deleted inline policy: {policy_name} from {role_name}")

            # ロールを削除
            iam_client.delete_role(RoleName=role_name)
            print(f"[OK] Deleted role: {role_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                print(f"[INFO] Role not found (already deleted): {role_name}")
            else:
                print(f"[WARNING] Failed to delete role {role_name}: {e}")


def main():
    print("=" * 80)
    print("bedrock-agentcore:actorId Condition Key の直接検証")
    print("=" * 80)

    # 引数チェック
    cleanup_mode = "--cleanup" in sys.argv

    # 設定読み込み
    config = load_config()
    account_id = get_account_id()

    # Memory 情報（Tenant A の Memory を使用）
    tenant_a_memory = config.get("memoryTenantA", config.get("memory", {}))
    memory_id = tenant_a_memory["memoryId"]
    strategy_id = tenant_a_memory["strategyId"]
    memory_arn = tenant_a_memory["memoryArn"]

    print(f"\n[INFO] Account ID: {account_id}")
    print(f"[INFO] Memory ID: {memory_id}")
    print(f"[INFO] Strategy ID: {strategy_id}")
    print(f"[INFO] Memory ARN: {memory_arn}")
    print(f"[INFO] Allowed actorId: {ALLOWED_ACTOR_ID}")
    print(f"[INFO] Denied actorId: {DENIED_ACTOR_ID}")

    # IAM / STS クライアント
    iam_client = boto3.client("iam", region_name=REGION)
    sts_client = boto3.client("sts", region_name=REGION)

    # クリーンアップモード
    if cleanup_mode:
        print("\n" + "-" * 80)
        print("Cleanup Mode: テストロールを削除")
        print("-" * 80)
        cleanup_roles(iam_client)
        print("\n[OK] Cleanup complete.")
        return

    # ==========================================
    # Step 1: テストロールの作成
    # ==========================================
    print("\n" + "-" * 80)
    print("Step 1: テストロールの作成")
    print("-" * 80)

    role_with_condition_arn = create_test_role_with_actorid_condition(
        iam_client, account_id, memory_arn
    )
    role_without_condition_arn = create_test_role_without_condition(
        iam_client, account_id, memory_arn
    )

    # IAM ポリシーの伝播待ち
    print("\n[INFO] Waiting 15 seconds for IAM policy propagation...")
    time.sleep(15)

    # ==========================================
    # Step 2: テスト実行
    # ==========================================
    print("\n" + "-" * 80)
    print("Step 2: テスト実行")
    print("-" * 80)

    results = []

    # ------------------------------------------------------------------
    # Test 1: Condition Key 付きロール + 一致する actorId (BatchCreate)
    # ------------------------------------------------------------------
    print(f"\n[TEST 1] Condition Key 付きロール + 一致する actorId ({ALLOWED_ACTOR_ID})")
    print(f"  API: BatchCreateMemoryRecords")
    print(f"  期待: 成功（actorId が Condition に一致）")
    try:
        creds1 = assume_role(sts_client, role_with_condition_arn, "actorid-test-1")
        result1 = test_batch_create_with_namespace(creds1, memory_id, strategy_id, ALLOWED_ACTOR_ID)
        print(f"  結果: {json.dumps(result1, indent=2, ensure_ascii=False)}")
        results.append(("1: With Condition + Match (BatchCreate)", result1))
    except ClientError as e:
        print(f"  [ERROR] AssumeRole failed: {e}")
        results.append(("1: With Condition + Match (BatchCreate)", {"success": False, "error": str(e)}))

    # ------------------------------------------------------------------
    # Test 2: Condition Key 付きロール + 不一致の actorId (BatchCreate)
    # ------------------------------------------------------------------
    print(f"\n[TEST 2] Condition Key 付きロール + 不一致の actorId ({DENIED_ACTOR_ID})")
    print(f"  API: BatchCreateMemoryRecords")
    print(f"  期待: AccessDeniedException（actorId が Condition に不一致）")
    try:
        creds2 = assume_role(sts_client, role_with_condition_arn, "actorid-test-2")
        result2 = test_batch_create_with_namespace(creds2, memory_id, strategy_id, DENIED_ACTOR_ID)
        print(f"  結果: {json.dumps(result2, indent=2, ensure_ascii=False)}")
        results.append(("2: With Condition + Mismatch (BatchCreate)", result2))
    except ClientError as e:
        print(f"  [ERROR] AssumeRole failed: {e}")
        results.append(("2: With Condition + Mismatch (BatchCreate)", {"success": False, "error": str(e)}))

    # ------------------------------------------------------------------
    # Test 3: Condition Key なしロール + 任意の actorId (BatchCreate)
    # ------------------------------------------------------------------
    print(f"\n[TEST 3] Condition Key なしロール + 任意の actorId ({DENIED_ACTOR_ID})")
    print(f"  API: BatchCreateMemoryRecords")
    print(f"  期待: 成功（Condition Key なし）")
    try:
        creds3 = assume_role(sts_client, role_without_condition_arn, "actorid-test-3")
        result3 = test_batch_create_with_namespace(creds3, memory_id, strategy_id, DENIED_ACTOR_ID)
        print(f"  結果: {json.dumps(result3, indent=2, ensure_ascii=False)}")
        results.append(("3: Without Condition (BatchCreate)", result3))
    except ClientError as e:
        print(f"  [ERROR] AssumeRole failed: {e}")
        results.append(("3: Without Condition (BatchCreate)", {"success": False, "error": str(e)}))

    # ------------------------------------------------------------------
    # Test 4: Condition Key 付きロール + 一致する actorId (Retrieve)
    # ------------------------------------------------------------------
    print(f"\n[TEST 4] Condition Key 付きロール + 一致する actorId ({ALLOWED_ACTOR_ID})")
    print(f"  API: RetrieveMemoryRecords")
    print(f"  期待: 成功（actorId が Condition に一致）")
    try:
        creds4 = assume_role(sts_client, role_with_condition_arn, "actorid-test-4")
        result4 = test_retrieve_records(creds4, memory_id, strategy_id, ALLOWED_ACTOR_ID)
        print(f"  結果: {json.dumps(result4, indent=2, ensure_ascii=False)}")
        results.append(("4: With Condition + Match (Retrieve)", result4))
    except ClientError as e:
        print(f"  [ERROR] AssumeRole failed: {e}")
        results.append(("4: With Condition + Match (Retrieve)", {"success": False, "error": str(e)}))

    # ------------------------------------------------------------------
    # Test 5: Condition Key 付きロール + 不一致の actorId (Retrieve)
    # ------------------------------------------------------------------
    print(f"\n[TEST 5] Condition Key 付きロール + 不一致の actorId ({DENIED_ACTOR_ID})")
    print(f"  API: RetrieveMemoryRecords")
    print(f"  期待: AccessDeniedException（actorId が Condition に不一致）")
    try:
        creds5 = assume_role(sts_client, role_with_condition_arn, "actorid-test-5")
        result5 = test_retrieve_records(creds5, memory_id, strategy_id, DENIED_ACTOR_ID)
        print(f"  結果: {json.dumps(result5, indent=2, ensure_ascii=False)}")
        results.append(("5: With Condition + Mismatch (Retrieve)", result5))
    except ClientError as e:
        print(f"  [ERROR] AssumeRole failed: {e}")
        results.append(("5: With Condition + Mismatch (Retrieve)", {"success": False, "error": str(e)}))

    # ------------------------------------------------------------------
    # Test 6: Condition Key 付きロール + ListActors
    # ------------------------------------------------------------------
    print(f"\n[TEST 6] Condition Key 付きロール + ListActors")
    print(f"  API: ListActors")
    print(f"  期待: Condition Key が ListActors に影響するか確認")
    try:
        creds6 = assume_role(sts_client, role_with_condition_arn, "actorid-test-6")
        result6 = test_list_actors(creds6, memory_id)
        print(f"  結果: {json.dumps(result6, indent=2, ensure_ascii=False)}")
        results.append(("6: With Condition + ListActors", result6))
    except ClientError as e:
        print(f"  [ERROR] AssumeRole failed: {e}")
        results.append(("6: With Condition + ListActors", {"success": False, "error": str(e)}))

    # ==========================================
    # Step 3: 結果分析
    # ==========================================
    print("\n" + "=" * 80)
    print("検証結果サマリー")
    print("=" * 80)

    for name, result in results:
        status = "[PASS]" if result.get("success") else "[FAIL]"
        if result.get("success"):
            detail = result.get("recordId") or result.get("recordCount", "") or result.get("actorCount", "")
            print(f"  {status} {name}: success (detail: {detail})")
        else:
            error_code = result.get("errorCode", "N/A")
            print(f"  {status} {name}: failed (errorCode: {error_code})")

    # ==========================================
    # Step 4: 判定
    # ==========================================
    print("\n" + "=" * 80)
    print("判定")
    print("=" * 80)

    test1_ok = results[0][1].get("success", False)  # Condition + Match -> should succeed
    test2_ok = results[1][1].get("success", False)  # Condition + Mismatch -> should fail
    test3_ok = results[2][1].get("success", False)  # No Condition -> should succeed
    test4_ok = results[3][1].get("success", False)  # Condition + Match (Retrieve) -> should succeed
    test5_ok = results[4][1].get("success", False)  # Condition + Mismatch (Retrieve) -> should fail

    # Condition Key が正常に機能するパターン:
    # Test 1: success, Test 2: fail (AccessDenied), Test 3: success
    # Test 4: success, Test 5: fail (AccessDenied)
    if test1_ok and not test2_ok and test3_ok and test4_ok and not test5_ok:
        test2_error = results[1][1].get("errorCode", "")
        test5_error = results[4][1].get("errorCode", "")
        if "AccessDenied" in test2_error and "AccessDenied" in test5_error:
            print("[PASS] actorId Condition Key は IAM レベルで正常に評価されている")
            print("  - Test 1 (一致 + BatchCreate): 成功")
            print("  - Test 2 (不一致 + BatchCreate): AccessDeniedException（期待通り）")
            print("  - Test 3 (Condition なし): 成功")
            print("  - Test 4 (一致 + Retrieve): 成功")
            print("  - Test 5 (不一致 + Retrieve): AccessDeniedException（期待通り）")
            print("\n  -> bedrock-agentcore:actorId Condition Key はサポートされている。")
            verdict = "PASS"
        else:
            print("[BLOCKED] actorId Condition Key の評価結果が不明確")
            print(f"  Test 2 error: {test2_error}")
            print(f"  Test 5 error: {test5_error}")
            verdict = "BLOCKED"
    elif test1_ok and test2_ok and test3_ok:
        print("[BLOCKED] actorId Condition Key は IAM レベルで評価されていない")
        print("  - Test 1 (一致): 成功")
        print("  - Test 2 (不一致): 成功（本来は失敗すべき）")
        print("  - Test 3 (Condition なし): 成功")
        print("\n  -> Condition Key を設定しても、不一致の actorId でアクセスが通る。")
        print("  -> 'bedrock-agentcore:actorId' Condition Key は API レベルで未サポートの可能性。")
        verdict = "BLOCKED"
    elif not test1_ok and not test2_ok:
        test1_error = results[0][1].get("errorCode", "")
        if "AccessDenied" in test1_error:
            print("[BLOCKED] actorId Condition Key により全アクセスが拒否されている")
            print("  - Test 1 (一致): AccessDeniedException")
            print("  - Test 2 (不一致): AccessDeniedException")
            print("\n  -> Condition Key は認識されるが、API が actorId コンテキストを提供していない。")
            print("  -> Null Condition（Condition Key の値が null）により全拒否になっている可能性。")
            verdict = "BLOCKED"
        else:
            print("[FAIL] 予期しないエラー")
            print(f"  Test 1 error: {results[0][1]}")
            print(f"  Test 2 error: {results[1][1]}")
            verdict = "FAIL"
    else:
        print("[FAIL] 予期しない結果パターン")
        for name, result in results:
            print(f"  {name}: {result}")
        verdict = "FAIL"

    # ==========================================
    # Step 5: クリーンアップ
    # ==========================================
    print("\n" + "-" * 80)
    print("Step 5: クリーンアップ")
    print("-" * 80)
    cleanup_roles(iam_client)

    # ==========================================
    # 最終結果
    # ==========================================
    print("\n" + "=" * 80)
    print(f"最終判定: {verdict}")
    print("=" * 80)

    # 結果を JSON ファイルに保存
    output = {
        "verdict": verdict,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "accountId": account_id,
            "region": REGION,
            "memoryId": memory_id,
            "strategyId": strategy_id,
            "memoryArn": memory_arn,
            "allowedActorId": ALLOWED_ACTOR_ID,
            "deniedActorId": DENIED_ACTOR_ID
        },
        "results": [
            {"name": name, "result": result} for name, result in results
        ]
    }

    output_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "actorid-test-results.json"
    )
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[OK] Results saved to: {output_file}")

    return verdict


if __name__ == "__main__":
    main()
