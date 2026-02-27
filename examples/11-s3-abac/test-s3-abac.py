#!/usr/bin/env python3
"""
S3 ABAC 統合テストスクリプト

4 つのテストケースを実行して、S3 オブジェクトタグベースの ABAC を検証する。

Test 1: Tenant A が自身のオブジェクトにアクセス成功
Test 2: Tenant B が自身のオブジェクトにアクセス成功
Test 3: Tenant A が Tenant B のオブジェクトにアクセス拒否
Test 4: Tenant B が Tenant A のオブジェクトにアクセス拒否
"""

import boto3
import json
import os
import sys
import time
from botocore.exceptions import ClientError

REGION = "us-east-1"
CONFIG_FILE = "phase11-config.json"


def load_config():
    """設定ファイルを読み込み"""
    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Config file not found: {CONFIG_FILE}")
        print("  Run: python3 setup-s3-buckets.py && python3 setup-iam-roles.py first")
        sys.exit(1)

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def assume_role_with_tags(role_arn, external_id, tenant_id):
    """
    STS AssumeRole を実行し、SessionTags で tenant_id を付与する。
    返り値は tenant_id タグ付きの一時的な認証情報を持つ S3 クライアント。
    """
    sts = boto3.client("sts", region_name=REGION)
    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=f"s3-abac-test-{tenant_id}",
        ExternalId=external_id,
        Tags=[{"Key": "tenant_id", "Value": tenant_id}],
    )
    credentials = response["Credentials"]
    s3_client = boto3.client(
        "s3",
        region_name=REGION,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )
    return s3_client


def test_get_object(s3_client, bucket_name, object_key, expect_success):
    """S3 GetObject を実行し、期待される結果と照合する"""
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        body = response["Body"].read().decode("utf-8")
        if expect_success:
            print(f"  [PASS] GetObject succeeded: {object_key}")
            print(f"    Content (first 50 chars): {body[:50]}")
            return True
        else:
            print(f"  [FAIL] GetObject should have been denied: {object_key}")
            return False
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if not expect_success and error_code == "AccessDenied":
            print(f"  [PASS] GetObject denied as expected: {object_key}")
            print(f"    Error: {error_code}")
            return True
        else:
            if expect_success:
                print(f"  [FAIL] GetObject unexpectedly denied: {object_key}")
                print(f"    Error: {error_code} - {e.response['Error']['Message']}")
            else:
                print(f"  [FAIL] Unexpected error: {error_code}")
                print(f"    Message: {e.response['Error']['Message']}")
            return False


def run_tests(config):
    """4 つのテストケースを実行"""
    bucket_name = config["bucket"]["bucketName"]
    role_a = config["roles"]["tenantA"]
    role_b = config["roles"]["tenantB"]
    objects_a = config["tenantA"]["objects"]
    objects_b = config["tenantB"]["objects"]

    results = []

    # Test 1: Tenant A が自身のオブジェクトにアクセス成功
    print("\n" + "-" * 60)
    print("[TEST 1] Tenant A accessing own objects (expect: SUCCESS)")
    print("-" * 60)
    s3_a = assume_role_with_tags(role_a["roleArn"], "tenant-a", "tenant-a")
    print(f"[INFO] AssumeRole succeeded: {role_a['roleName']} (tenant-a)")
    for obj_key in objects_a:
        result = test_get_object(s3_a, bucket_name, obj_key, expect_success=True)
        results.append(("Test 1", obj_key, result))

    # Test 2: Tenant B が自身のオブジェクトにアクセス成功
    print("\n" + "-" * 60)
    print("[TEST 2] Tenant B accessing own objects (expect: SUCCESS)")
    print("-" * 60)
    s3_b = assume_role_with_tags(role_b["roleArn"], "tenant-b", "tenant-b")
    print(f"[INFO] AssumeRole succeeded: {role_b['roleName']} (tenant-b)")
    for obj_key in objects_b:
        result = test_get_object(s3_b, bucket_name, obj_key, expect_success=True)
        results.append(("Test 2", obj_key, result))

    # Test 3: Tenant A が Tenant B のオブジェクトにアクセス拒否
    print("\n" + "-" * 60)
    print("[TEST 3] Tenant A accessing Tenant B objects (expect: DENIED)")
    print("-" * 60)
    for obj_key in objects_b:
        result = test_get_object(s3_a, bucket_name, obj_key, expect_success=False)
        results.append(("Test 3", obj_key, result))

    # Test 4: Tenant B が Tenant A のオブジェクトにアクセス拒否
    print("\n" + "-" * 60)
    print("[TEST 4] Tenant B accessing Tenant A objects (expect: DENIED)")
    print("-" * 60)
    for obj_key in objects_a:
        result = test_get_object(s3_b, bucket_name, obj_key, expect_success=False)
        results.append(("Test 4", obj_key, result))

    return results


def print_summary(results):
    """テスト結果のサマリを表示"""
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)

    passed = sum(1 for _, _, r in results if r)
    failed = sum(1 for _, _, r in results if not r)
    total = len(results)

    for test_name, obj_key, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {test_name}: {obj_key}")

    print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed}")

    if failed == 0:
        print("\n[OK] All tests passed! S3 ABAC is working correctly.")
        return 0
    else:
        print(f"\n[ERROR] {failed} test(s) failed.")
        return 1


def main():
    print("=" * 60)
    print("S3 ABAC Integration Tests")
    print("=" * 60)

    config = load_config()
    bucket_name = config["bucket"]["bucketName"]
    print(f"[INFO] S3 Bucket: {bucket_name}")
    print(f"[INFO] Tenant A Role: {config['roles']['tenantA']['roleName']}")
    print(f"[INFO] Tenant B Role: {config['roles']['tenantB']['roleName']}")

    results = run_tests(config)
    exit_code = print_summary(results)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
