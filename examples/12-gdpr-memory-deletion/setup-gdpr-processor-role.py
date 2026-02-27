#!/usr/bin/env python3
"""
Phase 12: GDPR Processor IAM ロール作成

GDPR Right to Erasure（忘れられる権利）対応のために、
Memory レコード削除のみを許可する最小権限の IAM ロールを作成する。

許可される操作:
- bedrock-agentcore:BatchDeleteMemoryRecords（バッチ削除）
- bedrock-agentcore:DeleteMemoryRecord（単体削除）
- bedrock-agentcore:RetrieveMemoryRecords（削除対象の検索）
- bedrock-agentcore:ListMemoryRecords（削除対象の一覧取得）

明示的に拒否される操作:
- bedrock-agentcore:BatchCreateMemoryRecords（新規作成）
- bedrock-agentcore:BatchUpdateMemoryRecords（更新）
- bedrock-agentcore:CreateMemory（Memory リソース作成）
- bedrock-agentcore:DeleteMemory（Memory リソース自体の削除）
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
GDPR_PROCESSOR_ROLE_NAME = "gdpr-memory-processor-role"

# Config ファイル
CONFIG_FILE = "phase12-config.json"


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Config file not found: {CONFIG_FILE}")
        print("  Copy phase12-config.json.example to phase12-config.json and edit it,")
        print("  or run setup-memory.py in examples/01-memory-api/ first.")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def get_account_id():
    """AWS アカウント ID を取得"""
    sts = boto3.client("sts", region_name=REGION)
    return sts.get_caller_identity()["Account"]


def create_trust_policy(account_id):
    """Trust Policy を作成

    GDPR Processor ロールは管理者のみが AssumeRole できるよう制限する。
    本番環境では Principal を特定の管理者ロール/ユーザーに限定すること。
    """
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
                        "sts:ExternalId": "gdpr-processor"
                    }
                }
            }
        ]
    }


def create_gdpr_delete_policy(memory_arn):
    """GDPR 削除専用ポリシーを作成

    最小権限の原則に従い、削除と検索操作のみを許可する。
    作成・更新・Memory リソース自体の削除は明示的に拒否する。
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowMemoryRecordDeletion",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:BatchDeleteMemoryRecords",
                    "bedrock-agentcore:DeleteMemoryRecord"
                ],
                "Resource": memory_arn
            },
            {
                "Sid": "AllowMemoryRecordRetrieval",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:RetrieveMemoryRecords",
                    "bedrock-agentcore:ListMemoryRecords",
                    "bedrock-agentcore:GetMemoryRecord"
                ],
                "Resource": memory_arn
            },
            {
                "Sid": "DenyMemoryRecordCreationAndUpdate",
                "Effect": "Deny",
                "Action": [
                    "bedrock-agentcore:BatchCreateMemoryRecords",
                    "bedrock-agentcore:BatchUpdateMemoryRecords"
                ],
                "Resource": "*"
            },
            {
                "Sid": "DenyMemoryResourceModification",
                "Effect": "Deny",
                "Action": [
                    "bedrock-agentcore:CreateMemory",
                    "bedrock-agentcore:DeleteMemory",
                    "bedrock-agentcore:UpdateMemory"
                ],
                "Resource": "*"
            }
        ]
    }


def create_gdpr_processor_role(iam_client, account_id, memory_arn):
    """GDPR Processor IAM ロールを作成"""
    trust_policy = create_trust_policy(account_id)
    delete_policy = create_gdpr_delete_policy(memory_arn)

    try:
        response = iam_client.create_role(
            RoleName=GDPR_PROCESSOR_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="GDPR Processor: Memory record deletion only (Right to Erasure)",
            Tags=[
                {"Key": "project", "Value": "bedrock-agentcore-cookbook"},
                {"Key": "phase", "Value": "12-gdpr-memory-deletion"},
                {"Key": "purpose", "Value": "gdpr-right-to-erasure"}
            ]
        )
        role_arn = response["Role"]["Arn"]
        print(f"[OK] GDPR Processor role created: {GDPR_PROCESSOR_ROLE_NAME}")
        print(f"  ARN: {role_arn}")

    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            print(f"[INFO] Role already exists: {GDPR_PROCESSOR_ROLE_NAME}")
            response = iam_client.get_role(RoleName=GDPR_PROCESSOR_ROLE_NAME)
            role_arn = response["Role"]["Arn"]

            # Trust Policy を更新
            iam_client.update_assume_role_policy(
                RoleName=GDPR_PROCESSOR_ROLE_NAME,
                PolicyDocument=json.dumps(trust_policy)
            )
            print(f"[OK] Trust policy updated")
        else:
            raise

    # Inline Policy を作成/更新
    iam_client.put_role_policy(
        RoleName=GDPR_PROCESSOR_ROLE_NAME,
        PolicyName="GDPRMemoryDeletePolicy",
        PolicyDocument=json.dumps(delete_policy)
    )
    print(f"[OK] Inline policy attached: GDPRMemoryDeletePolicy")

    return {
        "roleName": GDPR_PROCESSOR_ROLE_NAME,
        "roleArn": role_arn
    }


def save_config(config):
    """設定を JSON ファイルに保存"""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"[OK] Configuration saved: {os.path.abspath(CONFIG_FILE)}")


def main():
    parser = argparse.ArgumentParser(
        description="Phase 12: GDPR Processor IAM ロール作成"
    )
    parser.add_argument("--dry-run", action="store_true", help="実行せずに確認のみ")
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 12: GDPR Processor IAM Role Setup")
    print("=" * 60)

    # Config 読み込み
    config = load_config()
    account_id = config.get("accountId")
    memory_arn = config.get("memory", {}).get("memoryArn")

    if not account_id:
        account_id = get_account_id()
        config["accountId"] = account_id

    if not memory_arn:
        print("[ERROR] Memory ARN not found in config.")
        print("  Run setup-memory.py in examples/01-memory-api/ first.")
        sys.exit(1)

    print(f"[INFO] AWS Account: {account_id}")
    print(f"[INFO] Region: {REGION}")
    print(f"[INFO] Memory ARN: {memory_arn}")

    if args.dry_run:
        print("\n[INFO] Dry run mode - no resources will be created")
        print(f"  GDPR Processor Role: {GDPR_PROCESSOR_ROLE_NAME}")
        print(f"\n  Allowed actions:")
        print(f"    - bedrock-agentcore:BatchDeleteMemoryRecords")
        print(f"    - bedrock-agentcore:DeleteMemoryRecord")
        print(f"    - bedrock-agentcore:RetrieveMemoryRecords")
        print(f"    - bedrock-agentcore:ListMemoryRecords")
        print(f"    - bedrock-agentcore:GetMemoryRecord")
        print(f"\n  Denied actions:")
        print(f"    - bedrock-agentcore:BatchCreateMemoryRecords")
        print(f"    - bedrock-agentcore:BatchUpdateMemoryRecords")
        print(f"    - bedrock-agentcore:CreateMemory")
        print(f"    - bedrock-agentcore:DeleteMemory")
        print(f"    - bedrock-agentcore:UpdateMemory")
        return

    # IAM クライアント作成
    iam_client = boto3.client("iam", region_name=REGION)

    # GDPR Processor ロール作成
    print("\n[STEP 1] Creating GDPR Processor IAM Role...")
    try:
        role_info = create_gdpr_processor_role(iam_client, account_id, memory_arn)
        config["gdprProcessor"] = role_info
    except Exception as e:
        print(f"[ERROR] Failed to create GDPR Processor role: {e}")
        sys.exit(1)

    # Config 保存
    save_config(config)

    print("\n" + "=" * 60)
    print("[OK] GDPR Processor IAM Role setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Run: python3 gdpr-delete-user-memories.py --actor-id <actor_id>")
    print("  2. Run: python3 gdpr-audit-report.py")


if __name__ == "__main__":
    main()
