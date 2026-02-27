#!/usr/bin/env python3
"""
リソースクリーンアップスクリプト

Memory リソースと IAM ロールを削除する。
"""

import boto3
import json
import os
import sys
import argparse
from botocore.exceptions import ClientError

# リージョン
REGION = "us-east-1"

# Config ファイル
CONFIG_FILE = "phase5-config.json"


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[INFO] Config file not found: {CONFIG_FILE}")
        return None

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def delete_memory(client, memory_id):
    """Memory を削除（Strategy とレコードも自動削除される）"""
    try:
        client.delete_memory(memoryId=memory_id)
        print(f"[OK] Deleted Memory: {memory_id}")
        print(f"  (Strategies and records are automatically deleted)")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"[INFO] Memory not found: {memory_id}")
        else:
            print(f"[ERROR] Failed to delete Memory: {e}")


def delete_iam_role(iam_client, role_name):
    """IAM ロールを削除（Inline Policy も削除）"""
    try:
        # Inline Policy を削除
        try:
            iam_client.delete_role_policy(
                RoleName=role_name,
                PolicyName="MemoryABACPolicy"
            )
            print(f"[OK] Deleted inline policy: MemoryABACPolicy")
        except ClientError as e:
            if e.response["Error"]["Code"] != "NoSuchEntity":
                print(f"[WARN] Failed to delete inline policy: {e}")

        # ロール削除
        iam_client.delete_role(RoleName=role_name)
        print(f"[OK] Deleted role: {role_name}")

    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            print(f"[INFO] Role not found: {role_name}")
        else:
            print(f"[ERROR] Failed to delete role: {e}")


def delete_config_file():
    """Config ファイルを削除"""
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)
        print(f"[OK] Deleted config file: {CONFIG_FILE}")
    else:
        print(f"[INFO] Config file not found: {CONFIG_FILE}")


def main():
    parser = argparse.ArgumentParser(description="E2E Phase 5: クリーンアップ")
    parser.add_argument("--dry-run", action="store_true", help="削除対象の確認のみ")
    parser.add_argument("--skip-memory", action="store_true", help="Memory リソースをスキップ")
    parser.add_argument("--skip-iam", action="store_true", help="IAM ロールをスキップ")
    args = parser.parse_args()

    print("=" * 60)
    print("E2E Phase 5: Cleanup")
    print("=" * 60)

    # Config 読み込み
    config = load_config()

    if not config:
        print("[INFO] No config found. Nothing to clean up.")
        return

    print(f"[INFO] AWS Account: {config.get('accountId', 'N/A')}")
    print(f"[INFO] Region: {config.get('region', REGION)}")

    # ドライラン表示
    if args.dry_run:
        print("\n[INFO] Dry run mode - resources to be deleted:")
        if not args.skip_memory and "memory" in config:
            print(f"  - Memory: {config['memory']['memoryId']}")
            print(f"    (Strategies and records will be deleted automatically)")
        if not args.skip_iam and "roles" in config:
            print(f"  - IAM Role (Tenant A): {config['roles']['tenantA']['roleName']}")
            print(f"  - IAM Role (Tenant B): {config['roles']['tenantB']['roleName']}")
        print(f"  - Config file: {CONFIG_FILE}")
        return

    # Memory リソース削除
    if not args.skip_memory and "memory" in config:
        print("\n[STEP 1] Deleting Memory resources...")
        try:
            memory_client = boto3.client("bedrock-agentcore-control", region_name=REGION)
            memory_id = config["memory"]["memoryId"]
            delete_memory(memory_client, memory_id)
        except Exception as e:
            print(f"[ERROR] Failed to delete Memory: {e}")

    # IAM ロール削除
    if not args.skip_iam and "roles" in config:
        print("\n[STEP 2] Deleting IAM roles...")
        try:
            iam_client = boto3.client("iam", region_name=REGION)

            # Tenant A ロール削除
            print("[STEP 2.1] Deleting Tenant A role...")
            delete_iam_role(iam_client, config["roles"]["tenantA"]["roleName"])

            # Tenant B ロール削除
            print("[STEP 2.2] Deleting Tenant B role...")
            delete_iam_role(iam_client, config["roles"]["tenantB"]["roleName"])

        except Exception as e:
            print(f"[ERROR] Failed to delete IAM roles: {e}")

    # Config ファイル削除
    print("\n[STEP 3] Deleting config file...")
    delete_config_file()

    print("\n" + "=" * 60)
    print("[OK] Cleanup complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
