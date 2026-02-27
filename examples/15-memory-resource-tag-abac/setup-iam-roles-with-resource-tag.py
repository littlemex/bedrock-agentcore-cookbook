#!/usr/bin/env python3
"""
Memory ResourceTag ABAC IAM ロール作成スクリプト

Tenant A と Tenant B 用の IAM ロールを作成する。
- Trust Policy: STS AssumeRole + sts:TagSession 許可
- Inline Policy: aws:ResourceTag/tenant_id と aws:PrincipalTag/tenant_id の照合

このポリシーにより、Memory リソースの tenant_id タグと
STS セッションタグの tenant_id が一致する場合のみ
Memory API 操作を許可する。
"""

import boto3
import json
import os
import sys
import argparse
from botocore.exceptions import ClientError

REGION = "us-east-1"
CONFIG_FILE = "phase15-config.json"

TENANT_A_ROLE_NAME = "memory-restag-abac-tenant-a-role"
TENANT_B_ROLE_NAME = "memory-restag-abac-tenant-b-role"


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Config file not found: {CONFIG_FILE}")
        print("  Run: python3 setup-memory-with-tags.py first")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def create_trust_policy(account_id, tenant_id):
    """
    Trust Policy を作成

    AssumeRole と sts:TagSession を許可する。
    sts:TagSession が必要な理由:
    - AssumeRole 時に SessionTags（tenant_id）を付与するため
    - SessionTags がないと aws:PrincipalTag/tenant_id を参照できない
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
                "Action": ["sts:AssumeRole", "sts:TagSession"],
                "Condition": {
                    "StringEquals": {"sts:ExternalId": tenant_id}
                },
            }
        ],
    }


def create_memory_resource_tag_abac_policy():
    """
    Memory ResourceTag ABAC ポリシーを作成

    aws:ResourceTag/tenant_id == ${aws:PrincipalTag/tenant_id} の条件で、
    同一テナントの Memory リソースのみ操作を許可する。

    S3 ABAC（s3:ExistingObjectTag/tenant_id）と異なり、
    Memory API では aws:ResourceTag を使用する。
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowMemoryOperationsWithMatchingTag",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:BatchCreateMemoryRecords",
                    "bedrock-agentcore:BatchUpdateMemoryRecords",
                    "bedrock-agentcore:BatchDeleteMemoryRecords",
                    "bedrock-agentcore:RetrieveMemoryRecords",
                    "bedrock-agentcore:GetMemoryRecord",
                    "bedrock-agentcore:DeleteMemoryRecord",
                    "bedrock-agentcore:ListMemoryRecords",
                ],
                "Resource": "arn:aws:bedrock-agentcore:*:*:memory/*",
                "Condition": {
                    "StringEquals": {
                        "aws:ResourceTag/tenant_id": "${aws:PrincipalTag/tenant_id}"
                    }
                },
            },
            {
                "Sid": "AllowGetMemoryForTagCheck",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetMemory",
                ],
                "Resource": "arn:aws:bedrock-agentcore:*:*:memory/*",
                "Condition": {
                    "StringEquals": {
                        "aws:ResourceTag/tenant_id": "${aws:PrincipalTag/tenant_id}"
                    }
                },
            },
        ],
    }


def create_iam_role(iam_client, role_name, trust_policy, abac_policy, tenant_id):
    """IAM ロールを作成"""
    try:
        response = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=f"Memory ResourceTag ABAC Role for {tenant_id}",
            Tags=[
                {"Key": "project", "Value": "memory-resource-tag-abac"},
                {"Key": "tenant_id", "Value": tenant_id},
            ],
        )
        role_arn = response["Role"]["Arn"]
        print(f"[OK] Role created: {role_name}")
        print(f"  ARN: {role_arn}")

        # Inline Policy 追加
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName="MemoryResourceTagABACPolicy",
            PolicyDocument=json.dumps(abac_policy),
        )
        print(f"[OK] Inline policy attached: MemoryResourceTagABACPolicy")

        return {"roleName": role_name, "roleArn": role_arn, "tenantId": tenant_id}

    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            print(f"[INFO] Role already exists: {role_name}")
            response = iam_client.get_role(RoleName=role_name)
            role_arn = response["Role"]["Arn"]

            # Trust Policy を更新
            iam_client.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=json.dumps(trust_policy),
            )
            print(f"[OK] Trust policy updated")

            # Inline Policy を更新
            iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName="MemoryResourceTagABACPolicy",
                PolicyDocument=json.dumps(abac_policy),
            )
            print(f"[OK] Inline policy updated: MemoryResourceTagABACPolicy")

            return {"roleName": role_name, "roleArn": role_arn, "tenantId": tenant_id}
        else:
            raise


def save_config(config):
    """設定を JSON ファイルに保存"""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\n[OK] Configuration updated: {os.path.abspath(CONFIG_FILE)}")


def main():
    parser = argparse.ArgumentParser(
        description="Memory ResourceTag ABAC IAM ロール作成スクリプト"
    )
    parser.add_argument("--dry-run", action="store_true", help="実行せずに確認のみ")
    args = parser.parse_args()

    print("=" * 60)
    print("Memory ResourceTag ABAC: IAM Roles Setup")
    print("=" * 60)

    config = load_config()
    account_id = config["accountId"]

    print(f"[INFO] AWS Account: {account_id}")
    print(f"[INFO] Memory A ARN: {config.get('memoryA', {}).get('memoryArn', 'N/A')}")
    print(f"[INFO] Memory B ARN: {config.get('memoryB', {}).get('memoryArn', 'N/A')}")

    if args.dry_run:
        print("[INFO] Dry run mode - no resources will be created")
        print(f"  Tenant A Role: {TENANT_A_ROLE_NAME}")
        print(f"  Tenant B Role: {TENANT_B_ROLE_NAME}")
        print("\n[INFO] ABAC Policy (ResourceTag):")
        policy = create_memory_resource_tag_abac_policy()
        print(json.dumps(policy, indent=2))
        return

    iam_client = boto3.client("iam", region_name=REGION)
    abac_policy = create_memory_resource_tag_abac_policy()

    print("\n[INFO] ABAC Policy:")
    print(json.dumps(abac_policy, indent=2))

    # Step 1: Tenant A ロール作成
    print("\n[STEP 1] Creating Tenant A IAM Role...")
    trust_policy_a = create_trust_policy(account_id, "tenant-a")
    role_a_info = create_iam_role(
        iam_client, TENANT_A_ROLE_NAME, trust_policy_a, abac_policy, "tenant-a"
    )

    # Step 2: Tenant B ロール作成
    print("\n[STEP 2] Creating Tenant B IAM Role...")
    trust_policy_b = create_trust_policy(account_id, "tenant-b")
    role_b_info = create_iam_role(
        iam_client, TENANT_B_ROLE_NAME, trust_policy_b, abac_policy, "tenant-b"
    )

    # Config 保存
    config["roles"] = {
        "tenantA": role_a_info,
        "tenantB": role_b_info,
    }
    save_config(config)

    print("\n" + "=" * 60)
    print("[OK] IAM roles setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Wait ~10 seconds for IAM policy propagation")
    print("  2. Run: python3 test-resource-tag-abac.py")


if __name__ == "__main__":
    main()
