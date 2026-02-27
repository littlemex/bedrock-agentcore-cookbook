#!/usr/bin/env python3
"""
E2E Phase 5: Memory 作成（boto3 経由）

AgentCore Memory リソースを boto3 で作成する。
"""

import json
import os
import sys
import argparse
import boto3
from botocore.exceptions import ClientError

# リージョン
REGION = "us-east-1"

# Memory リソース名（パターン: [a-zA-Z][a-zA-Z0-9_]{0,47}）
MEMORY_NAME = "e2e_phase5_memory"

# Config ファイル
CONFIG_FILE = "phase5-config.json"


def get_account_id():
    """AWS アカウント ID を取得"""
    sts = boto3.client("sts", region_name=REGION)
    return sts.get_caller_identity()["Account"]


def get_existing_memory_id():
    """既存の config から Memory ID を取得"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            return config.get("memory", {}).get("memoryId")
        except Exception:
            return None
    return None


def create_memory(client, memory_name):
    """Memory を作成"""
    print(f"[INFO] Creating Memory: {memory_name}")

    # 既存の config から Memory ID を取得
    existing_memory_id = get_existing_memory_id()
    if existing_memory_id:
        print(f"[INFO] Found existing Memory ID in config: {existing_memory_id}")
        try:
            response = client.get_memory(memoryId=existing_memory_id)
            memory = response["memory"]

            print(f"[OK] Using existing Memory")
            print(f"  ID: {memory['id']}")
            print(f"  ARN: {memory['arn']}")
            print(f"  Name: {memory['name']}")

            strategies = memory.get("strategies", [])
            if strategies:
                strategy = strategies[0]
                print(f"  Strategy ID: {strategy['strategyId']}")
                print(f"  Strategy Name: {strategy['name']}")

                return {
                    "memoryId": memory["id"],
                    "memoryName": memory["name"],
                    "memoryArn": memory["arn"],
                    "strategyId": strategy["strategyId"],
                    "strategyName": strategy["name"]
                }
            else:
                print(f"[WARN] No strategies found in Memory")
                return {
                    "memoryId": memory["id"],
                    "memoryName": memory["name"],
                    "memoryArn": memory["arn"],
                    "strategyId": None,
                    "strategyName": None
                }
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                print(f"[WARN] Memory not found: {existing_memory_id}")
                print(f"[INFO] Will create new Memory")
            else:
                raise

    # Memory 作成
    try:
        response = client.create_memory(
            name=memory_name,
            description="E2E Phase 5: Memory ABAC テナント分離検証",
            eventExpiryDuration=30,
            memoryStrategies=[
                {
                    "semanticMemoryStrategy": {
                        "name": "default_strategy",
                        "description": "Default semantic strategy"
                    }
                }
            ]
        )

        memory = response["memory"]
        memory_id = memory["id"]
        memory_arn = memory["arn"]

        print(f"[OK] Memory created")
        print(f"  ID: {memory_id}")
        print(f"  ARN: {memory_arn}")

        # Memory の詳細情報を取得して Strategy ID を取得
        response = client.get_memory(memoryId=memory_id)
        memory = response["memory"]

        strategies = memory.get("strategies", [])
        if not strategies:
            raise Exception("No strategies found in Memory")

        strategy = strategies[0]
        strategy_id = strategy["strategyId"]
        strategy_name = strategy["name"]

        print(f"  Strategy ID: {strategy_id}")
        print(f"  Strategy Name: {strategy_name}")

        return {
            "memoryId": memory_id,
            "memoryName": memory_name,
            "memoryArn": memory_arn,
            "strategyId": strategy_id,
            "strategyName": strategy_name
        }
    except ClientError as e:
        if e.response["Error"]["Code"] == "ValidationException" and "already exists" in str(e):
            print(f"[INFO] Memory already exists, trying to retrieve...")
            # list_memories で取得
            response = client.list_memories()
            for mem in response.get("memories", []):
                # get_memory で詳細を取得して名前を確認
                details = client.get_memory(memoryId=mem["id"])
                if details["memory"]["name"] == memory_name:
                    memory = details["memory"]
                    strategies = memory.get("strategies", [])

                    print(f"[OK] Using existing Memory")
                    print(f"  ID: {memory['id']}")
                    print(f"  ARN: {memory['arn']}")

                    if strategies:
                        strategy = strategies[0]
                        print(f"  Strategy ID: {strategy['strategyId']}")
                        print(f"  Strategy Name: {strategy['name']}")

                        return {
                            "memoryId": memory["id"],
                            "memoryName": memory["name"],
                            "memoryArn": memory["arn"],
                            "strategyId": strategy["strategyId"],
                            "strategyName": strategy["name"]
                        }
                    else:
                        return {
                            "memoryId": memory["id"],
                            "memoryName": memory["name"],
                            "memoryArn": memory["arn"],
                            "strategyId": None,
                            "strategyName": None
                        }

            print(f"[ERROR] Could not find Memory: {memory_name}")
            raise
        else:
            raise


def save_config(config):
    """設定を JSON ファイルに保存"""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"[OK] Configuration saved to: {os.path.abspath(CONFIG_FILE)}")


def main():
    parser = argparse.ArgumentParser(description="E2E Phase 5: Memory 作成")
    parser.add_argument("--dry-run", action="store_true", help="実行せずに確認のみ")
    args = parser.parse_args()

    print("=" * 60)
    print("E2E Phase 5: Memory Setup (boto3)")
    print("=" * 60)

    # AWS アカウント確認
    try:
        account_id = get_account_id()
        print(f"[INFO] AWS Account: {account_id}")
        print(f"[INFO] Region: {REGION}")
    except Exception as e:
        print(f"[ERROR] Failed to get AWS account: {e}")
        sys.exit(1)

    if args.dry_run:
        print("[INFO] Dry run mode - no resources will be created")
        print(f"  Memory: {MEMORY_NAME}")
        return

    config = {
        "accountId": account_id,
        "region": REGION
    }

    # Memory 作成
    print("\n[STEP 1] Creating Memory...")
    try:
        client = boto3.client("bedrock-agentcore-control", region_name=REGION)
        memory_info = create_memory(client, MEMORY_NAME)
        config["memory"] = memory_info
    except Exception as e:
        print(f"[ERROR] Failed to create memory: {e}")
        sys.exit(1)

    # Config 保存
    save_config(config)

    print("\n" + "=" * 60)
    print("[OK] Memory setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Run: python3 setup-iam-roles.py")


if __name__ == "__main__":
    main()
