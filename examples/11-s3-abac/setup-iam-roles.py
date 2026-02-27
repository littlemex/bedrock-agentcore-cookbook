#!/usr/bin/env python3
"""
S3 ABAC IAM ロール作成スクリプト

Tenant A と Tenant B 用の IAM ロールを作成する。
- Trust Policy: STS AssumeRole + sts:TagSession 許可
- Inline Policy: S3 ABAC ポリシー（s3:ExistingObjectTag/tenant_id と aws:PrincipalTag/tenant_id の照合）
"""

import boto3
import json
import os
import sys
import argparse
from botocore.exceptions import ClientError

REGION = "us-east-1"
CONFIG_FILE = "phase11-config.json"

TENANT_A_ROLE_NAME = "s3-abac-tenant-a-role"
TENANT_B_ROLE_NAME = "s3-abac-tenant-b-role"


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Config file not found: {CONFIG_FILE}")
        print("  Run: python3 setup-s3-buckets.py first")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def create_trust_policy(account_id, tenant_id):
    """Trust Policy を作成（AssumeRole with External ID + sts:TagSession 許可）"""
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


def create_s3_abac_policy(bucket_name):
    """
    S3 ABAC ポリシーを作成

    s3:ExistingObjectTag/tenant_id == ${aws:PrincipalTag/tenant_id} の条件で、
    同一テナントのオブジェクトのみアクセスを許可する。
    """
    bucket_arn = f"arn:aws:s3:::{bucket_name}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowS3GetObjectWithMatchingTag",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:GetObjectTagging"],
                "Resource": f"{bucket_arn}/*",
                "Condition": {
                    "StringEquals": {
                        "s3:ExistingObjectTag/tenant_id": "${aws:PrincipalTag/tenant_id}"
                    }
                },
            },
            {
                "Sid": "AllowS3PutObjectWithTag",
                "Effect": "Allow",
                "Action": ["s3:PutObject", "s3:PutObjectTagging"],
                "Resource": f"{bucket_arn}/*",
            },
            {
                "Sid": "AllowListBucket",
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": bucket_arn,
            },
        ],
    }


def create_iam_role(iam_client, role_name, trust_policy, s3_policy, tenant_id):
    """IAM ロールを作成"""
    try:
        response = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=f"S3 ABAC Role for {tenant_id}",
            Tags=[
                {"Key": "project", "Value": "s3-abac-example"},
                {"Key": "tenant_id", "Value": tenant_id},
            ],
        )
        role_arn = response["Role"]["Arn"]
        print(f"[OK] Role created: {role_name}")
        print(f"  ARN: {role_arn}")

        # Inline Policy 追加
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName="S3ABACPolicy",
            PolicyDocument=json.dumps(s3_policy),
        )
        print(f"[OK] Inline policy attached: S3ABACPolicy")

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
                PolicyName="S3ABACPolicy",
                PolicyDocument=json.dumps(s3_policy),
            )
            print(f"[OK] Inline policy updated: S3ABACPolicy")

            return {"roleName": role_name, "roleArn": role_arn, "tenantId": tenant_id}
        else:
            raise


def save_config(config):
    """設定を JSON ファイルに保存"""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"[OK] Configuration updated: {os.path.abspath(CONFIG_FILE)}")


def main():
    parser = argparse.ArgumentParser(description="S3 ABAC IAM ロール作成スクリプト")
    parser.add_argument("--dry-run", action="store_true", help="実行せずに確認のみ")
    args = parser.parse_args()

    print("=" * 60)
    print("S3 ABAC IAM Roles Setup")
    print("=" * 60)

    config = load_config()
    account_id = config["accountId"]
    bucket_name = config["bucket"]["bucketName"]

    print(f"[INFO] AWS Account: {account_id}")
    print(f"[INFO] S3 Bucket: {bucket_name}")

    if args.dry_run:
        print("[INFO] Dry run mode - no resources will be created")
        print(f"  Tenant A Role: {TENANT_A_ROLE_NAME}")
        print(f"  Tenant B Role: {TENANT_B_ROLE_NAME}")
        return

    iam_client = boto3.client("iam", region_name=REGION)

    # Step 1: Tenant A ロール作成
    print("\n[STEP 1] Creating Tenant A IAM Role...")
    trust_policy_a = create_trust_policy(account_id, "tenant-a")
    s3_policy = create_s3_abac_policy(bucket_name)
    role_a_info = create_iam_role(
        iam_client, TENANT_A_ROLE_NAME, trust_policy_a, s3_policy, "tenant-a"
    )

    # Step 2: Tenant B ロール作成
    print("\n[STEP 2] Creating Tenant B IAM Role...")
    trust_policy_b = create_trust_policy(account_id, "tenant-b")
    role_b_info = create_iam_role(
        iam_client, TENANT_B_ROLE_NAME, trust_policy_b, s3_policy, "tenant-b"
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
    print("  2. Run: python3 test-s3-abac.py")


if __name__ == "__main__":
    main()
