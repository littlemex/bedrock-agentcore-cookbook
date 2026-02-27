#!/usr/bin/env python3
"""
AuthPolicyTable テストユーザーデータ投入スクリプト

Pre Token Generation Lambda がユーザー認証ポリシーを取得できるよう、
テストユーザーデータを AuthPolicyTable に投入する。

テストユーザー:
- admin@tenant-a.example.com: tenant-a の管理者（フルアクセス）
- user@tenant-a.example.com: tenant-a の一般ユーザー（制限付き）
- admin@tenant-b.example.com: tenant-b の管理者
- readonly@tenant-b.example.com: tenant-b の読み取り専用ユーザー

使い方:
    python3 seed-test-users.py
    python3 seed-test-users.py --config phase13-config.json
    python3 seed-test-users.py --clear  # 既存データを削除してから投入
"""

import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError


def load_config(config_path: str) -> dict:
    """設定ファイルを読み込む"""
    with open(config_path, "r") as f:
        return json.load(f)


def get_test_users() -> list:
    """
    テストユーザーデータを定義する

    Returns:
        テストユーザーアイテムのリスト
    """
    return [
        # tenant-a 管理者
        {
            "email": "admin@tenant-a.example.com",
            "tenant_id": "tenant-a",
            "role": "admin",
            "groups": ["administrators", "developers", "viewers"],
            "allowed_tools": ["*"],
            "display_name": "Admin User (Tenant A)",
            "status": "active",
        },
        # tenant-a 一般ユーザー
        {
            "email": "user@tenant-a.example.com",
            "tenant_id": "tenant-a",
            "role": "user",
            "groups": ["developers", "viewers"],
            "allowed_tools": [
                "code-review",
                "documentation",
                "testing",
            ],
            "display_name": "Regular User (Tenant A)",
            "status": "active",
        },
        # tenant-b 管理者
        {
            "email": "admin@tenant-b.example.com",
            "tenant_id": "tenant-b",
            "role": "admin",
            "groups": ["administrators", "developers", "viewers"],
            "allowed_tools": ["*"],
            "display_name": "Admin User (Tenant B)",
            "status": "active",
        },
        # tenant-b 読み取り専用ユーザー
        {
            "email": "readonly@tenant-b.example.com",
            "tenant_id": "tenant-b",
            "role": "readonly",
            "groups": ["viewers"],
            "allowed_tools": [
                "documentation",
            ],
            "display_name": "Read-Only User (Tenant B)",
            "status": "active",
        },
    ]


def clear_existing_data(table, users: list) -> None:
    """
    既存のテストデータを削除する

    Args:
        table: DynamoDB Table リソース
        users: 削除対象ユーザーのリスト
    """
    print("[START] 既存テストデータを削除中...")

    deleted_count = 0
    with table.batch_writer() as batch:
        for user in users:
            try:
                batch.delete_item(Key={"email": user["email"]})
                deleted_count += 1
            except ClientError as e:
                print(f"[WARNING] 削除エラー ({user['email']}): {e}")

    print(f"[OK] {deleted_count} 件のアイテムを削除しました")


def seed_test_users(table, users: list) -> None:
    """
    テストユーザーデータを投入する

    Args:
        table: DynamoDB Table リソース
        users: 投入するユーザーデータのリスト
    """
    print(f"[START] {len(users)} 件のテストユーザーを投入中...")

    with table.batch_writer() as batch:
        for user in users:
            batch.put_item(Item=user)
            print(f"  [OK] {user['email']} (tenant: {user['tenant_id']}, role: {user['role']})")

    print(f"[OK] {len(users)} 件のテストユーザーを投入しました")


def verify_data(table, users: list) -> bool:
    """
    投入したデータを検証する

    Args:
        table: DynamoDB Table リソース
        users: 検証対象ユーザーデータのリスト

    Returns:
        True: すべてのデータが正常
        False: データに問題あり
    """
    print("\n[START] データ検証中...")

    all_ok = True
    for user in users:
        try:
            response = table.get_item(Key={"email": user["email"]})
            if "Item" in response:
                item = response["Item"]
                # 主要フィールドの検証
                if item["tenant_id"] == user["tenant_id"] and item["role"] == user["role"]:
                    print(f"  [OK] {user['email']}")
                else:
                    print(f"  [NG] {user['email']} - データ不一致")
                    all_ok = False
            else:
                print(f"  [NG] {user['email']} - アイテムが見つかりません")
                all_ok = False
        except ClientError as e:
            print(f"  [NG] {user['email']} - エラー: {e}")
            all_ok = False

    if all_ok:
        print("[OK] すべてのデータが正常です")
    else:
        print("[NG] データに問題があります")

    return all_ok


def print_summary(users: list) -> None:
    """投入データのサマリーを表示する"""
    print("\n--- テストユーザー一覧 ---")
    print(f"{'email':<40} {'tenant_id':<12} {'role':<10} {'groups'}")
    print("-" * 90)
    for user in users:
        groups_str = ", ".join(user["groups"])
        print(f"{user['email']:<40} {user['tenant_id']:<12} {user['role']:<10} {groups_str}")
    print("-" * 90)
    print(f"合計: {len(users)} ユーザー")


def main():
    parser = argparse.ArgumentParser(
        description="AuthPolicyTable にテストユーザーデータを投入する"
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
    parser.add_argument(
        "--clear",
        action="store_true",
        help="既存データを削除してから投入する",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="投入せずにデータ内容のみ表示する",
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

    # テストユーザーデータ
    users = get_test_users()

    # dry-run モード
    if args.dry_run:
        print("[NOTE] dry-run モード: データは投入されません")
        print_summary(users)
        print("\n投入されるデータ (JSON):")
        print(json.dumps(users, indent=2, ensure_ascii=False))
        return

    # DynamoDB リソース作成
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    # テーブル存在確認
    try:
        table.load()
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"[NG] テーブル '{table_name}' が見つかりません。")
            print("先に setup-dynamodb-table.py を実行してください。")
            sys.exit(1)
        raise

    print(f"テーブル: {table_name} (region: {region})")

    # 既存データの削除
    if args.clear:
        clear_existing_data(table, users)

    # テストユーザー投入
    seed_test_users(table, users)

    # 検証
    verify_data(table, users)

    # サマリー表示
    print_summary(users)

    print(f"\n[OK] テストユーザーデータ投入完了")


if __name__ == "__main__":
    main()
