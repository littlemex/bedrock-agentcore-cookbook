#!/usr/bin/env python3
"""
E2E Phase 5: テナント別 Memory 作成（boto3 経由）

各テナント用に別の Memory リソースを作成してテナント分離を実現する。
"""

import json
import os
import sys
import argparse
import boto3
from botocore.exceptions import ClientError

# リージョン
REGION = "us-east-1"

# Config ファイル
CONFIG_FILE = "phase5-config.json"


def get_account_id():
    """AWS アカウント ID を取得"""
    sts = boto3.client("sts", region_name=REGION)
    return sts.get_caller_identity()["Account"]


def create_memory(client, memory_name, tenant_id):
    """Memory を作成"""
    print(f"[INFO] Creating Memory for {tenant_id}: {memory_name}")

    try:
        response = client.create_memory(
            name=memory_name,
            description=f"E2E Phase 5: Memory for {tenant_id}",
            eventExpiryDuration=30,
            memoryStrategies=[
                {
                    "semanticMemoryStrategy": {
                        "name": f"{tenant_id.replace('-', '_')}_strategy",
                        "description": f"Strategy for {tenant_id}"
                    }
                }
            ]
        )

        memory = response["memory"]
        strategies = memory.get("strategies", [])
        strategy = strategies[0] if strategies else None

        print(f"[OK] Memory created")
        print(f"  ID: {memory['id']}")
        print(f"  ARN: {memory['arn']}")
        print(f"  Name: {memory['name']}")
        if strategy:
            print(f"  Strategy ID: {strategy['strategyId']}")
            print(f"  Strategy Name: {strategy['name']}")

        return {
            "memoryId": memory["id"],
            "memoryName": memory["name"],
            "memoryArn": memory["arn"],
            "strategyId": strategy["strategyId"] if strategy else None,
            "strategyName": strategy["name"] if strategy else None
        }

    except ClientError as e:
        print(f"[ERROR] Failed to create Memory: {e}")
        raise


def load_or_create_config():
    """既存 config を読み込むか、新規作成"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    else:
        account_id = get_account_id()
        return {
            "accountId": account_id,
            "region": REGION
        }


def save_config(config):
    """設定を JSON ファイルに保存"""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"[OK] Configuration saved: {os.path.abspath(CONFIG_FILE)}")


def main():
    parser = argparse.ArgumentParser(description="E2E Phase 5: テナント別 Memory 作成")
    parser.add_argument("--dry-run", action="store_true", help="実行せずに確認のみ")
    args = parser.parse_args()

    print("=" * 60)
    print("E2E Phase 5: Multi-Tenant Memory Setup")
    print("=" * 60)

    # Config 読み込み
    config = load_or_create_config()
    account_id = config["accountId"]

    print(f"[INFO] AWS Account: {account_id}")
    print(f"[INFO] Region: {REGION}")

    if args.dry_run:
        print("[INFO] Dry run mode - no resources will be created")
        return

    # AWS クライアント作成
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # Step 1: Tenant A Memory 作成
    print("\n[STEP 1] Creating Memory for Tenant A...")
    try:
        memory_a = create_memory(client, "e2e_phase5_memory_tenant_a", "tenant-a")
        config["memoryTenantA"] = memory_a
    except Exception as e:
        print(f"[ERROR] Failed to create Tenant A memory: {e}")
        sys.exit(1)

    # Step 2: Tenant B Memory 作成
    print("\n[STEP 2] Creating Memory for Tenant B...")
    try:
        memory_b = create_memory(client, "e2e_phase5_memory_tenant_b", "tenant-b")
        config["memoryTenantB"] = memory_b
    except Exception as e:
        print(f"[ERROR] Failed to create Tenant B memory: {e}")
        sys.exit(1)

    # Config 保存
    save_config(config)

    print("\n" + "=" * 60)
    print("[OK] Multi-tenant Memory setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Run: python3 setup-iam-roles-multi-tenant.py")


if __name__ == "__main__":
    main()
