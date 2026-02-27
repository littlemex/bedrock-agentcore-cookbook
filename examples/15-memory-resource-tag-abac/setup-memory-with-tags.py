#!/usr/bin/env python3
"""
Memory リソース作成スクリプト（ResourceTag ABAC 用）

Tenant A と Tenant B 用の Memory を作成し、
リソースタグ（tenant_id）を付与する。

検証内容:
- Memory 作成時にタグを付与
- ListTagsForResource でタグの付与を確認
- aws:ResourceTag/tenant_id Condition Key の前提条件を構築
"""

import boto3
import json
import os
import sys
import time
import argparse
from botocore.exceptions import ClientError

REGION = "us-east-1"
CONFIG_FILE = "phase15-config.json"

MEMORY_NAME_A = "resource_tag_abac_tenant_a"
MEMORY_NAME_B = "resource_tag_abac_tenant_b"
MEMORY_NAME_NO_TAG = "resource_tag_abac_no_tag"


def get_account_id():
    """AWS アカウント ID を取得"""
    sts = boto3.client("sts", region_name=REGION)
    return sts.get_caller_identity()["Account"]


def create_memory_with_tags(control_client, memory_name, tenant_id):
    """
    Memory を作成し、リソースタグを付与する。

    Bedrock AgentCore の CreateMemory API がタグパラメータを
    サポートしている場合は直接付与し、サポートしていない場合は
    TagResource API を使用する。
    """
    print(f"\n[INFO] Creating Memory: {memory_name} (tenant_id={tenant_id})")

    # Memory 作成
    try:
        response = control_client.create_memory(
            name=memory_name,
            description=f"ResourceTag ABAC test memory for {tenant_id}",
            eventExpiryDuration=30,
            memoryStrategies=[
                {
                    "semanticMemoryStrategy": {
                        "name": "default_strategy",
                        "description": "Default semantic strategy for ABAC test",
                    }
                }
            ],
        )

        memory = response["memory"]
        memory_id = memory["id"]
        memory_arn = memory["arn"]

        print(f"[OK] Memory created")
        print(f"  ID: {memory_id}")
        print(f"  ARN: {memory_arn}")

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ValidationException" and "already exists" in str(e):
            print(f"[INFO] Memory may already exist, searching...")
            memory_info = find_existing_memory(control_client, memory_name)
            if memory_info:
                memory_id = memory_info["memoryId"]
                memory_arn = memory_info["memoryArn"]
                print(f"[OK] Found existing Memory: {memory_id}")
            else:
                print(f"[ERROR] Memory exists but could not be found")
                raise
        else:
            raise

    # Memory が ACTIVE になるまで待機
    print(f"[INFO] Waiting for Memory to become ACTIVE...")
    memory_info = wait_for_memory_active(control_client, memory_id)

    # Strategy ID を取得
    strategy_id = None
    strategy_name = None
    if memory_info and "strategies" in memory_info:
        strategies = memory_info.get("strategies", [])
        if strategies:
            strategy_id = strategies[0].get("strategyId")
            strategy_name = strategies[0].get("name")
            print(f"  Strategy ID: {strategy_id}")
            print(f"  Strategy Name: {strategy_name}")

    # タグを付与
    print(f"[INFO] Tagging Memory with tenant_id={tenant_id}...")
    tag_memory(control_client, memory_arn, tenant_id)

    # タグの確認
    print(f"[INFO] Verifying tags...")
    verify_tags(control_client, memory_arn, tenant_id)

    return {
        "memoryId": memory_id,
        "memoryName": memory_name,
        "memoryArn": memory_arn,
        "strategyId": strategy_id,
        "strategyName": strategy_name,
        "tenantId": tenant_id,
    }


def find_existing_memory(control_client, memory_name):
    """既存の Memory を名前で検索"""
    try:
        response = control_client.list_memories()
        for mem in response.get("memories", []):
            details = control_client.get_memory(memoryId=mem["id"])
            memory = details["memory"]
            if memory.get("name") == memory_name:
                return {
                    "memoryId": memory["id"],
                    "memoryArn": memory["arn"],
                }
    except ClientError as e:
        print(f"[WARNING] Failed to list memories: {e}")
    return None


def wait_for_memory_active(control_client, memory_id, max_wait=120, interval=5):
    """Memory が ACTIVE になるまで待機"""
    elapsed = 0
    while elapsed < max_wait:
        try:
            response = control_client.get_memory(memoryId=memory_id)
            memory = response["memory"]
            status = memory.get("status", "UNKNOWN")
            print(f"  Status: {status} ({elapsed}s elapsed)")

            if status == "ACTIVE":
                return memory

            if status in ("FAILED", "DELETE_IN_PROGRESS"):
                print(f"[ERROR] Memory entered terminal state: {status}")
                return None

        except ClientError as e:
            print(f"  [WARNING] GetMemory failed: {e}")

        time.sleep(interval)
        elapsed += interval

    print(f"[ERROR] Memory did not become ACTIVE within {max_wait}s")
    return None


def tag_memory(control_client, memory_arn, tenant_id):
    """
    Memory にリソースタグを付与する。

    TagResource API を使用して tenant_id タグを設定する。
    API がサポートされていない場合はエラーメッセージを記録する。
    """
    try:
        control_client.tag_resource(
            resourceArn=memory_arn,
            tags={
                "tenant_id": tenant_id,
                "project": "memory-resource-tag-abac",
            },
        )
        print(f"[OK] Tags applied to Memory: {memory_arn}")
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        print(f"[ERROR] TagResource failed: {error_code}")
        print(f"  Message: {error_msg}")
        print(f"  [NOTE] TagResource API may not be supported for Memory resources.")
        raise
    except AttributeError:
        print(f"[ERROR] tag_resource method not available in this SDK version")
        print(f"  [NOTE] Memory API may not support TagResource yet.")
        raise


def verify_tags(control_client, memory_arn, expected_tenant_id):
    """
    ListTagsForResource でタグの付与を確認する。
    """
    try:
        response = control_client.list_tags_for_resource(resourceArn=memory_arn)
        tags = response.get("tags", {})
        print(f"[INFO] Tags on {memory_arn}:")
        for key, value in tags.items():
            print(f"  {key}: {value}")

        if tags.get("tenant_id") == expected_tenant_id:
            print(f"[OK] tenant_id tag verified: {expected_tenant_id}")
        else:
            actual = tags.get("tenant_id", "<not found>")
            print(f"[FAIL] tenant_id mismatch: expected={expected_tenant_id}, actual={actual}")

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        print(f"[ERROR] ListTagsForResource failed: {error_code}")
        print(f"  Message: {error_msg}")
    except AttributeError:
        print(f"[ERROR] list_tags_for_resource method not available in this SDK version")


def create_memory_without_tags(control_client, memory_name):
    """
    タグなしの Memory を作成する（Null Condition 検証用）。

    aws:ResourceTag/tenant_id が設定されていない Memory に対して、
    ABAC ポリシーがアクセスを拒否することを検証するために使用する。
    """
    print(f"\n[INFO] Creating Memory without tags: {memory_name}")

    try:
        response = control_client.create_memory(
            name=memory_name,
            description="ResourceTag ABAC test: no tenant_id tag (Null Condition test)",
            eventExpiryDuration=30,
            memoryStrategies=[
                {
                    "semanticMemoryStrategy": {
                        "name": "default_strategy",
                        "description": "Default semantic strategy for Null Condition test",
                    }
                }
            ],
        )

        memory = response["memory"]
        memory_id = memory["id"]
        memory_arn = memory["arn"]

        print(f"[OK] Memory created (no tags)")
        print(f"  ID: {memory_id}")
        print(f"  ARN: {memory_arn}")

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ValidationException" and "already exists" in str(e):
            print(f"[INFO] Memory may already exist, searching...")
            memory_info = find_existing_memory(control_client, memory_name)
            if memory_info:
                memory_id = memory_info["memoryId"]
                memory_arn = memory_info["memoryArn"]
                print(f"[OK] Found existing Memory: {memory_id}")
            else:
                print(f"[ERROR] Memory exists but could not be found")
                raise
        else:
            raise

    # Memory が ACTIVE になるまで待機
    print(f"[INFO] Waiting for Memory to become ACTIVE...")
    memory_info = wait_for_memory_active(control_client, memory_id)

    strategy_id = None
    strategy_name = None
    if memory_info and "strategies" in memory_info:
        strategies = memory_info.get("strategies", [])
        if strategies:
            strategy_id = strategies[0].get("strategyId")
            strategy_name = strategies[0].get("name")
            print(f"  Strategy ID: {strategy_id}")
            print(f"  Strategy Name: {strategy_name}")

    # タグは付与しない（Null Condition テスト用）
    print(f"[INFO] No tags applied (intentional for Null Condition test)")

    return {
        "memoryId": memory_id,
        "memoryName": memory_name,
        "memoryArn": memory_arn,
        "strategyId": strategy_id,
        "strategyName": strategy_name,
        "tenantId": None,
    }


def save_config(config):
    """設定を JSON ファイルに保存"""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\n[OK] Configuration saved: {os.path.abspath(CONFIG_FILE)}")


def main():
    parser = argparse.ArgumentParser(
        description="Memory ResourceTag ABAC: Memory 作成 + タグ付与スクリプト"
    )
    parser.add_argument("--dry-run", action="store_true", help="実行せずに確認のみ")
    args = parser.parse_args()

    print("=" * 60)
    print("Memory ResourceTag ABAC: Setup Memory with Tags")
    print("=" * 60)

    account_id = get_account_id()
    print(f"[INFO] AWS Account: {account_id}")
    print(f"[INFO] Region: {REGION}")

    if args.dry_run:
        print("[INFO] Dry run mode - no resources will be created")
        print(f"  Memory A: {MEMORY_NAME_A} (tenant_id=tenant-a)")
        print(f"  Memory B: {MEMORY_NAME_B} (tenant_id=tenant-b)")
        return

    control_client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    config = {
        "accountId": account_id,
        "region": REGION,
    }

    # Step 1: Tenant A の Memory 作成
    print("\n[STEP 1] Creating Tenant A Memory with tags...")
    try:
        memory_a = create_memory_with_tags(control_client, MEMORY_NAME_A, "tenant-a")
        config["memoryA"] = memory_a
    except Exception as e:
        print(f"[ERROR] Failed to create Tenant A Memory: {e}")
        print("[NOTE] If TagResource is not supported, see README.md for alternatives.")
        # Config を部分的に保存して再実行可能にする
        save_config(config)
        sys.exit(1)

    # Step 2: Tenant B の Memory 作成
    print("\n[STEP 2] Creating Tenant B Memory with tags...")
    try:
        memory_b = create_memory_with_tags(control_client, MEMORY_NAME_B, "tenant-b")
        config["memoryB"] = memory_b
    except Exception as e:
        print(f"[ERROR] Failed to create Tenant B Memory: {e}")
        print("[NOTE] If TagResource is not supported, see README.md for alternatives.")
        save_config(config)
        sys.exit(1)

    # Step 3: タグなし Memory の作成（Null Condition テスト用）
    print("\n[STEP 3] Creating Memory without tags (Null Condition test)...")
    try:
        memory_no_tag = create_memory_without_tags(control_client, MEMORY_NAME_NO_TAG)
        config["memoryNoTag"] = memory_no_tag
    except Exception as e:
        print(f"[ERROR] Failed to create no-tag Memory: {e}")
        save_config(config)
        sys.exit(1)

    # Config 保存
    save_config(config)

    print("\n" + "=" * 60)
    print("[OK] Memory setup with tags complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Run: python3 setup-iam-roles-with-resource-tag.py")
    print("  2. Run: python3 test-resource-tag-abac.py")


if __name__ == "__main__":
    main()
