#!/usr/bin/env python3
"""
Memory ResourceTag ABAC リソースクリーンアップスクリプト

setup-memory-with-tags.py と setup-iam-roles.py で作成したリソースを削除する。
- Memory リソース（Tenant A, Tenant B）
- IAM ロールとインラインポリシー
- 設定ファイル
"""

import boto3
import json
import os
import sys
import argparse
from botocore.exceptions import ClientError

REGION = "us-east-1"
CONFIG_FILE = "phase15-config.json"

ROLE_NAMES = [
    "memory-restag-abac-tenant-a-role",
    "memory-restag-abac-tenant-b-role",
]


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[WARNING] Config file not found: {CONFIG_FILE}")
        return None

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def delete_memory(control_client, memory_id, memory_name):
    """Memory リソースを削除"""
    try:
        control_client.delete_memory(memoryId=memory_id)
        print(f"[OK] Memory deleted: {memory_name} ({memory_id})")
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ResourceNotFoundException":
            print(f"[INFO] Memory not found: {memory_name} ({memory_id})")
        else:
            print(f"[ERROR] Failed to delete Memory {memory_name}: {error_code}")
            print(f"  Message: {e.response['Error']['Message']}")


def delete_iam_role(iam_client, role_name):
    """IAM ロールを削除（Inline Policy を先に削除）"""
    try:
        # Inline Policy を列挙して削除
        policies = iam_client.list_role_policies(RoleName=role_name)
        for policy_name in policies.get("PolicyNames", []):
            iam_client.delete_role_policy(
                RoleName=role_name, PolicyName=policy_name
            )
            print(f"[OK] Inline policy deleted: {policy_name} from {role_name}")

        # Managed Policy をデタッチ
        attached = iam_client.list_attached_role_policies(RoleName=role_name)
        for policy in attached.get("AttachedPolicies", []):
            iam_client.detach_role_policy(
                RoleName=role_name, PolicyArn=policy["PolicyArn"]
            )
            print(f"[OK] Managed policy detached: {policy['PolicyName']}")

        # ロールを削除
        iam_client.delete_role(RoleName=role_name)
        print(f"[OK] Role deleted: {role_name}")

    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            print(f"[INFO] Role does not exist: {role_name}")
        else:
            print(f"[ERROR] Failed to delete role {role_name}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Memory ResourceTag ABAC リソースクリーンアップスクリプト"
    )
    parser.add_argument("--dry-run", action="store_true", help="実行せずに確認のみ")
    args = parser.parse_args()

    print("=" * 60)
    print("Memory ResourceTag ABAC: Resource Cleanup")
    print("=" * 60)

    config = load_config()

    if args.dry_run:
        print("[INFO] Dry run mode - no resources will be deleted")
        if config:
            mem_a = config.get("memoryA", {})
            mem_b = config.get("memoryB", {})
            mem_no_tag = config.get("memoryNoTag", {})
            print(f"  Memory A: {mem_a.get('memoryName', 'N/A')} ({mem_a.get('memoryId', 'N/A')})")
            print(f"  Memory B: {mem_b.get('memoryName', 'N/A')} ({mem_b.get('memoryId', 'N/A')})")
            if mem_no_tag.get("memoryId"):
                print(f"  Memory (no tag): {mem_no_tag.get('memoryName', 'N/A')} ({mem_no_tag.get('memoryId', 'N/A')})")
        print(f"  IAM Roles: {', '.join(ROLE_NAMES)}")
        print(f"  Config file: {CONFIG_FILE}")
        return

    # Step 1: Memory リソースの削除
    print(f"\n[STEP 1] Deleting Memory resources...")
    if config:
        control_client = boto3.client("bedrock-agentcore-control", region_name=REGION)

        # Memory A
        mem_a = config.get("memoryA", {})
        if mem_a.get("memoryId"):
            delete_memory(control_client, mem_a["memoryId"], mem_a.get("memoryName", "N/A"))

        # Memory B
        mem_b = config.get("memoryB", {})
        if mem_b.get("memoryId"):
            delete_memory(control_client, mem_b["memoryId"], mem_b.get("memoryName", "N/A"))

        # Memory (no tag) - Null Condition テスト用
        mem_no_tag = config.get("memoryNoTag", {})
        if mem_no_tag.get("memoryId"):
            delete_memory(control_client, mem_no_tag["memoryId"], mem_no_tag.get("memoryName", "N/A"))
    else:
        print("[INFO] No config file, skipping Memory deletion...")

    # Step 2: IAM ロールの削除
    print(f"\n[STEP 2] Deleting IAM roles...")
    iam_client = boto3.client("iam", region_name=REGION)
    for role_name in ROLE_NAMES:
        delete_iam_role(iam_client, role_name)

    # Step 3: 設定ファイルの削除
    print(f"\n[STEP 3] Removing config file...")
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)
        print(f"[OK] Config file removed: {CONFIG_FILE}")
    else:
        print(f"[INFO] Config file not found: {CONFIG_FILE}")

    print("\n" + "=" * 60)
    print("[OK] Cleanup complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
