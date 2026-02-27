#!/usr/bin/env python3
"""
S3 ABAC リソースクリーンアップスクリプト

setup-s3-buckets.py と setup-iam-roles.py で作成したリソースを削除する。
- S3 バケット内の全オブジェクトを削除
- S3 バケットを削除
- IAM ロール（Inline Policy 含む）を削除
- 設定ファイルを削除
"""

import boto3
import json
import os
import sys
import argparse
from botocore.exceptions import ClientError

REGION = "us-east-1"
CONFIG_FILE = "phase11-config.json"

ROLE_NAMES = [
    "s3-abac-tenant-a-role",
    "s3-abac-tenant-b-role",
]


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[WARNING] Config file not found: {CONFIG_FILE}")
        return None

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def delete_bucket_objects(s3_client, bucket_name):
    """バケット内の全オブジェクトを削除"""
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket_name):
            objects = page.get("Contents", [])
            if not objects:
                continue
            delete_keys = [{"Key": obj["Key"]} for obj in objects]
            s3_client.delete_objects(
                Bucket=bucket_name, Delete={"Objects": delete_keys}
            )
            print(f"[OK] Deleted {len(delete_keys)} objects from {bucket_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchBucket":
            print(f"[INFO] Bucket does not exist: {bucket_name}")
        else:
            raise


def delete_bucket(s3_client, bucket_name):
    """S3 バケットを削除"""
    try:
        delete_bucket_objects(s3_client, bucket_name)
        s3_client.delete_bucket(Bucket=bucket_name)
        print(f"[OK] Bucket deleted: {bucket_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchBucket":
            print(f"[INFO] Bucket does not exist: {bucket_name}")
        else:
            print(f"[ERROR] Failed to delete bucket {bucket_name}: {e}")


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
        description="S3 ABAC リソースクリーンアップスクリプト"
    )
    parser.add_argument("--dry-run", action="store_true", help="実行せずに確認のみ")
    args = parser.parse_args()

    print("=" * 60)
    print("S3 ABAC Resource Cleanup")
    print("=" * 60)

    config = load_config()

    if args.dry_run:
        print("[INFO] Dry run mode - no resources will be deleted")
        if config:
            bucket_name = config.get("bucket", {}).get("bucketName", "N/A")
            print(f"  Bucket: {bucket_name}")
        print(f"  IAM Roles: {', '.join(ROLE_NAMES)}")
        print(f"  Config file: {CONFIG_FILE}")
        return

    # Step 1: S3 バケットの削除
    if config and "bucket" in config:
        bucket_name = config["bucket"]["bucketName"]
        print(f"\n[STEP 1] Deleting S3 bucket: {bucket_name}")
        s3_client = boto3.client("s3", region_name=REGION)
        delete_bucket(s3_client, bucket_name)
    else:
        print("\n[STEP 1] No bucket information in config, skipping...")

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
