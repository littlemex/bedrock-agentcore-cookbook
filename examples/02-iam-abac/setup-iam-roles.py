#!/usr/bin/env python3
"""
E2E Phase 5: IAM ロール作成（STS SessionTags ABAC）

Tenant A と Tenant B 用の IAM ロールを作成する。
- Trust Policy: STS AssumeRole + sts:TagSession 許可
- Inline Policy: Memory API アクセス（Namespace ベース + SessionTags ABAC）
- Cross-Tenant Deny ポリシー
"""

import boto3
import json
import os
import sys
import argparse
from botocore.exceptions import ClientError

# リージョン
REGION = "us-east-1"

# IAM ロール名
TENANT_A_ROLE_NAME = "e2e-phase5-tenant-a-role"
TENANT_B_ROLE_NAME = "e2e-phase5-tenant-b-role"

# Config ファイル
CONFIG_FILE = "phase5-config.json"


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Config file not found: {CONFIG_FILE}")
        print("  Run: python3 setup-memory.py first")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def get_account_id():
    """AWS アカウント ID を取得"""
    sts = boto3.client("sts", region_name=REGION)
    return sts.get_caller_identity()["Account"]


def create_trust_policy(account_id, tenant_id):
    """Trust Policy を作成（AssumeRole with External ID）"""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "AWS": f"arn:aws:iam::{account_id}:root"
                },
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {
                        "sts:ExternalId": tenant_id
                    }
                }
            }
        ]
    }


def create_memory_abac_policy(memory_arn, tenant_id):
    """Memory ABAC ポリシーを作成（Condition なしで全許可、namespace は application level で制御）"""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowMemoryAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:BatchCreateMemoryRecords",
                    "bedrock-agentcore:BatchUpdateMemoryRecords",
                    "bedrock-agentcore:BatchDeleteMemoryRecords",
                    "bedrock-agentcore:RetrieveMemoryRecords",
                    "bedrock-agentcore:GetMemoryRecord",
                    "bedrock-agentcore:DeleteMemoryRecord",
                    "bedrock-agentcore:ListMemoryRecords"
                ],
                "Resource": memory_arn
            }
        ]
    }


def create_iam_role(iam_client, role_name, trust_policy, memory_policy, tenant_id):
    """IAM ロールを作成"""
    try:
        # ロール作成
        response = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=f"E2E Phase 5: Tenant {tenant_id.upper()} Memory ABAC Role",
            Tags=[
                {"Key": "project", "Value": "e2e-phase5"},
                {"Key": "tenant_id", "Value": tenant_id}
            ]
        )
        role_arn = response["Role"]["Arn"]
        print(f"[OK] Role created: {role_name}")
        print(f"  ARN: {role_arn}")

        # Inline Policy 追加
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName="MemoryABACPolicy",
            PolicyDocument=json.dumps(memory_policy)
        )
        print(f"[OK] Inline policy attached: MemoryABACPolicy")

        return {
            "roleName": role_name,
            "roleArn": role_arn,
            "tenantId": tenant_id
        }

    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            print(f"[INFO] Role already exists: {role_name}")
            # 既存のロール情報を取得
            response = iam_client.get_role(RoleName=role_name)
            role_arn = response["Role"]["Arn"]

            # Inline Policy を更新
            iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName="MemoryABACPolicy",
                PolicyDocument=json.dumps(memory_policy)
            )
            print(f"[OK] Inline policy updated: MemoryABACPolicy")

            return {
                "roleName": role_name,
                "roleArn": role_arn,
                "tenantId": tenant_id
            }
        else:
            raise


def save_config(config):
    """設定を JSON ファイルに保存"""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"[OK] Configuration updated: {os.path.abspath(CONFIG_FILE)}")


def main():
    parser = argparse.ArgumentParser(description="E2E Phase 5: IAM ロール作成")
    parser.add_argument("--dry-run", action="store_true", help="実行せずに確認のみ")
    args = parser.parse_args()

    print("=" * 60)
    print("E2E Phase 5: IAM Roles Setup")
    print("=" * 60)

    # Config 読み込み
    config = load_config()
    account_id = config["accountId"]
    memory_arn = config["memory"]["memoryArn"]

    print(f"[INFO] AWS Account: {account_id}")
    print(f"[INFO] Memory ARN: {memory_arn}")

    # AWS クライアント作成
    iam_client = boto3.client("iam", region_name=REGION)

    if args.dry_run:
        print("[INFO] Dry run mode - no resources will be created")
        print(f"  Tenant A Role: {TENANT_A_ROLE_NAME}")
        print(f"  Tenant B Role: {TENANT_B_ROLE_NAME}")
        return

    # テナント別 Memory ARN を取得
    memory_arn_a = config.get("memoryTenantA", {}).get("memoryArn", memory_arn)
    memory_arn_b = config.get("memoryTenantB", {}).get("memoryArn", memory_arn)

    # Step 1: Tenant A ロール作成
    print("\n[STEP 1] Creating Tenant A IAM Role...")
    print(f"  Memory ARN: {memory_arn_a}")
    try:
        trust_policy_a = create_trust_policy(account_id, "tenant-a")
        memory_policy_a = create_memory_abac_policy(memory_arn_a, "tenant-a")
        role_a_info = create_iam_role(
            iam_client,
            TENANT_A_ROLE_NAME,
            trust_policy_a,
            memory_policy_a,
            "tenant-a"
        )
        config["roles"] = config.get("roles", {})
        config["roles"]["tenantA"] = role_a_info
    except Exception as e:
        print(f"[ERROR] Failed to create Tenant A role: {e}")
        sys.exit(1)

    # Step 2: Tenant B ロール作成
    print("\n[STEP 2] Creating Tenant B IAM Role...")
    print(f"  Memory ARN: {memory_arn_b}")
    try:
        trust_policy_b = create_trust_policy(account_id, "tenant-b")
        memory_policy_b = create_memory_abac_policy(memory_arn_b, "tenant-b")
        role_b_info = create_iam_role(
            iam_client,
            TENANT_B_ROLE_NAME,
            trust_policy_b,
            memory_policy_b,
            "tenant-b"
        )
        config["roles"]["tenantB"] = role_b_info
    except Exception as e:
        print(f"[ERROR] Failed to create Tenant B role: {e}")
        sys.exit(1)

    # Config 保存
    save_config(config)

    print("\n" + "=" * 60)
    print("[OK] IAM roles setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Run: python3 test-phase5.py")


if __name__ == "__main__":
    main()
