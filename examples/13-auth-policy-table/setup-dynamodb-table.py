#!/usr/bin/env python3
"""
AuthPolicyTable DynamoDB テーブル作成スクリプト

Pre Token Generation Lambda が参照する認証ポリシーテーブルを作成する。

テーブル設計:
- テーブル名: AuthPolicyTable
- Partition Key: email (String) - ユーザーの一意識別子
- GSI: TenantIdIndex (tenant_id) - テナント単位での検索用
- BillingMode: PAY_PER_REQUEST (オンデマンド)

使い方:
    python3 setup-dynamodb-table.py
    python3 setup-dynamodb-table.py --config phase13-config.json
"""

import argparse
import json
import sys
import time

import boto3
from botocore.exceptions import ClientError


def load_config(config_path: str) -> dict:
    """設定ファイルを読み込む"""
    with open(config_path, "r") as f:
        return json.load(f)


def create_auth_policy_table(
    dynamodb_client,
    table_name: str,
    region: str,
) -> dict:
    """
    AuthPolicyTable を作成する

    Args:
        dynamodb_client: boto3 DynamoDB client
        table_name: テーブル名
        region: AWS リージョン

    Returns:
        テーブル作成レスポンス
    """
    print(f"[START] AuthPolicyTable '{table_name}' を作成します (region: {region})")

    try:
        response = dynamodb_client.create_table(
            TableName=table_name,
            KeySchema=[
                {
                    "AttributeName": "email",
                    "KeyType": "HASH",
                },
            ],
            AttributeDefinitions=[
                {
                    "AttributeName": "email",
                    "AttributeType": "S",
                },
                {
                    "AttributeName": "tenant_id",
                    "AttributeType": "S",
                },
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "TenantIdIndex",
                    "KeySchema": [
                        {
                            "AttributeName": "tenant_id",
                            "KeyType": "HASH",
                        },
                    ],
                    "Projection": {
                        "ProjectionType": "ALL",
                    },
                },
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=[
                {"Key": "Project", "Value": "AgentCoreVerification"},
                {"Key": "Phase", "Value": "13"},
                {"Key": "Purpose", "Value": "AuthPolicy"},
            ],
        )

        print(f"[OK] テーブル作成リクエスト送信: {response['TableDescription']['TableStatus']}")
        return response

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"[WARNING] テーブル '{table_name}' は既に存在します")
            return None
        raise


def wait_for_table_active(dynamodb_client, table_name: str, timeout: int = 60) -> bool:
    """
    テーブルが ACTIVE になるまで待機する

    Args:
        dynamodb_client: boto3 DynamoDB client
        table_name: テーブル名
        timeout: タイムアウト秒数

    Returns:
        True: テーブルが ACTIVE
        False: タイムアウト
    """
    print(f"テーブル '{table_name}' が ACTIVE になるまで待機中...")

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = dynamodb_client.describe_table(TableName=table_name)
            status = response["Table"]["TableStatus"]
            if status == "ACTIVE":
                print(f"[OK] テーブル '{table_name}' は ACTIVE です")
                return True
            print(f"  現在のステータス: {status}")
            time.sleep(2)
        except ClientError:
            time.sleep(2)

    print(f"[NG] タイムアウト: テーブルが {timeout} 秒以内に ACTIVE になりませんでした")
    return False


def describe_table(dynamodb_client, table_name: str) -> None:
    """テーブル情報を表示する"""
    try:
        response = dynamodb_client.describe_table(TableName=table_name)
        table = response["Table"]

        print("\n--- テーブル情報 ---")
        print(f"テーブル名: {table['TableName']}")
        print(f"ステータス: {table['TableStatus']}")
        print(f"ARN: {table['TableArn']}")
        print(f"アイテム数: {table.get('ItemCount', 0)}")
        print(f"サイズ (bytes): {table.get('TableSizeBytes', 0)}")

        print("\nキースキーマ:")
        for key in table["KeySchema"]:
            print(f"  {key['AttributeName']} ({key['KeyType']})")

        if "GlobalSecondaryIndexes" in table:
            print("\nGSI:")
            for gsi in table["GlobalSecondaryIndexes"]:
                print(f"  {gsi['IndexName']}:")
                for key in gsi["KeySchema"]:
                    print(f"    {key['AttributeName']} ({key['KeyType']})")
                print(f"    Projection: {gsi['Projection']['ProjectionType']}")
                print(f"    Status: {gsi['IndexStatus']}")

        print("---")

    except ClientError as e:
        print(f"[NG] テーブル情報取得エラー: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="AuthPolicyTable DynamoDB テーブルを作成する"
    )
    parser.add_argument(
        "--config",
        default="phase13-config.json",
        help="設定ファイルのパス (default: phase13-config.json)",
    )
    parser.add_argument(
        "--table-name",
        default=None,
        help="テーブル名 (設定ファイルを上書き)",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS リージョン (設定ファイルを上書き)",
    )
    args = parser.parse_args()

    # 設定の読み込み
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"[WARNING] 設定ファイル '{args.config}' が見つかりません。デフォルト値を使用します。")
        config = {}

    table_name = args.table_name or config.get("table_name", "AuthPolicyTable")
    region = args.region or config.get("region", "us-east-1")

    # DynamoDB クライアント作成
    dynamodb_client = boto3.client("dynamodb", region_name=region)

    # テーブル作成
    result = create_auth_policy_table(dynamodb_client, table_name, region)

    if result is not None:
        # テーブルが ACTIVE になるまで待機
        if not wait_for_table_active(dynamodb_client, table_name):
            print("[NG] テーブル作成に失敗しました")
            sys.exit(1)

    # テーブル情報を表示
    describe_table(dynamodb_client, table_name)

    print(f"\n[OK] AuthPolicyTable セットアップ完了: {table_name}")


if __name__ == "__main__":
    main()
