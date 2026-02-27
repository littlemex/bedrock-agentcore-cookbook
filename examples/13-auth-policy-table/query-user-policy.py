#!/usr/bin/env python3
"""
AuthPolicyTable ユーザーポリシー取得スクリプト

Email アドレスからユーザーの認証ポリシー情報を取得する。
Pre Token Generation Lambda と同等のクエリロジックを検証できる。

使い方:
    python3 query-user-policy.py --email admin@tenant-a.example.com
    python3 query-user-policy.py --tenant tenant-a
    python3 query-user-policy.py --list-all
"""

import argparse
import json
import sys

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


def load_config(config_path: str) -> dict:
    """設定ファイルを読み込む"""
    with open(config_path, "r") as f:
        return json.load(f)


def query_by_email(table, email: str) -> dict | None:
    """
    Email からユーザーポリシーを取得する (GetItem)

    Pre Token Generation Lambda で使用するのと同等のクエリ。

    Args:
        table: DynamoDB Table リソース
        email: ユーザーのメールアドレス

    Returns:
        ユーザーポリシーアイテム、存在しない場合は None
    """
    print(f"[START] Email でユーザーポリシーを取得: {email}")

    try:
        response = table.get_item(Key={"email": email})

        if "Item" in response:
            item = response["Item"]
            print(f"[OK] ユーザーが見つかりました")
            return item
        else:
            print(f"[WARNING] ユーザーが見つかりません: {email}")
            return None

    except ClientError as e:
        print(f"[NG] クエリエラー: {e}")
        return None


def query_by_tenant(table, tenant_id: str) -> list:
    """
    TenantId GSI でテナントのユーザー一覧を取得する (Query)

    Args:
        table: DynamoDB Table リソース
        tenant_id: テナント ID

    Returns:
        テナントに属するユーザーのリスト
    """
    print(f"[START] テナントのユーザー一覧を取得: {tenant_id}")

    try:
        response = table.query(
            IndexName="TenantIdIndex",
            KeyConditionExpression=Key("tenant_id").eq(tenant_id),
        )

        items = response.get("Items", [])
        print(f"[OK] {len(items)} 件のユーザーが見つかりました")
        return items

    except ClientError as e:
        print(f"[NG] クエリエラー: {e}")
        return []


def scan_all_users(table) -> list:
    """
    テーブル内のすべてのユーザーを取得する (Scan)

    注意: 本番環境では Scan は推奨されません。検証用途のみ。

    Args:
        table: DynamoDB Table リソース

    Returns:
        すべてのユーザーのリスト
    """
    print("[START] すべてのユーザーを取得中...")

    try:
        items = []
        response = table.scan()
        items.extend(response.get("Items", []))

        # ページネーション対応
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))

        print(f"[OK] {len(items)} 件のユーザーが見つかりました")
        return items

    except ClientError as e:
        print(f"[NG] スキャンエラー: {e}")
        return []


def format_user_policy(item: dict) -> str:
    """
    ユーザーポリシーを見やすくフォーマットする

    Args:
        item: DynamoDB アイテム

    Returns:
        フォーマット済み文字列
    """
    lines = [
        "--- ユーザーポリシー ---",
        f"Email:         {item.get('email', 'N/A')}",
        f"Tenant ID:     {item.get('tenant_id', 'N/A')}",
        f"Role:          {item.get('role', 'N/A')}",
        f"Status:        {item.get('status', 'N/A')}",
        f"Display Name:  {item.get('display_name', 'N/A')}",
    ]

    groups = item.get("groups", [])
    if groups:
        lines.append(f"Groups:        {', '.join(groups)}")
    else:
        lines.append("Groups:        (none)")

    allowed_tools = item.get("allowed_tools", [])
    if allowed_tools:
        lines.append(f"Allowed Tools: {', '.join(allowed_tools)}")
    else:
        lines.append("Allowed Tools: (none)")

    lines.append("---")

    return "\n".join(lines)


def format_user_list(items: list) -> str:
    """
    ユーザー一覧を表形式でフォーマットする

    Args:
        items: DynamoDB アイテムのリスト

    Returns:
        フォーマット済み文字列
    """
    if not items:
        return "(ユーザーなし)"

    lines = [
        f"{'email':<40} {'tenant_id':<12} {'role':<10} {'status':<8} {'groups'}",
        "-" * 95,
    ]

    for item in items:
        groups_str = ", ".join(item.get("groups", []))
        lines.append(
            f"{item.get('email', 'N/A'):<40} "
            f"{item.get('tenant_id', 'N/A'):<12} "
            f"{item.get('role', 'N/A'):<10} "
            f"{item.get('status', 'N/A'):<8} "
            f"{groups_str}"
        )

    lines.append("-" * 95)
    lines.append(f"合計: {len(items)} ユーザー")

    return "\n".join(lines)


def simulate_pre_token_claims(item: dict) -> dict:
    """
    Pre Token Generation Lambda が生成するクレームをシミュレートする

    Args:
        item: DynamoDB アイテム

    Returns:
        JWT クレームに追加される属性の辞書
    """
    claims = {}

    if item.get("tenant_id"):
        claims["custom:tenant_id"] = item["tenant_id"]
    if item.get("role"):
        claims["custom:role"] = item["role"]
    if item.get("groups"):
        claims["custom:groups"] = json.dumps(item["groups"])
    if item.get("allowed_tools"):
        claims["custom:allowed_tools"] = json.dumps(item["allowed_tools"])

    return claims


def main():
    parser = argparse.ArgumentParser(
        description="AuthPolicyTable からユーザーポリシーを取得する"
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

    # クエリモード（排他選択）
    query_group = parser.add_mutually_exclusive_group(required=True)
    query_group.add_argument(
        "--email",
        help="Email でユーザーポリシーを取得する",
    )
    query_group.add_argument(
        "--tenant",
        help="テナント ID でユーザー一覧を取得する (GSI: TenantIdIndex)",
    )
    query_group.add_argument(
        "--list-all",
        action="store_true",
        help="すべてのユーザーを一覧表示する (Scan)",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="結果を JSON 形式で出力する",
    )
    parser.add_argument(
        "--simulate-claims",
        action="store_true",
        help="Pre Token Generation Lambda のクレーム生成をシミュレートする",
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

    print(f"テーブル: {table_name} (region: {region})\n")

    # Email クエリ
    if args.email:
        item = query_by_email(table, args.email)
        if item is None:
            sys.exit(1)

        if args.output_json:
            print(json.dumps(item, indent=2, ensure_ascii=False, default=str))
        else:
            print(format_user_policy(item))

        if args.simulate_claims:
            claims = simulate_pre_token_claims(item)
            print("\n--- Pre Token Generation クレーム (シミュレート) ---")
            print(json.dumps(claims, indent=2, ensure_ascii=False))
            print("---")

    # テナント ID クエリ（GSI）
    elif args.tenant:
        items = query_by_tenant(table, args.tenant)
        if not items:
            print(f"[WARNING] テナント '{args.tenant}' にユーザーが存在しません")
            sys.exit(1)

        if args.output_json:
            print(json.dumps(items, indent=2, ensure_ascii=False, default=str))
        else:
            print(format_user_list(items))

    # 全ユーザー一覧
    elif args.list_all:
        items = scan_all_users(table)
        if not items:
            print("[WARNING] テーブルにデータがありません")
            sys.exit(1)

        if args.output_json:
            print(json.dumps(items, indent=2, ensure_ascii=False, default=str))
        else:
            print(format_user_list(items))


if __name__ == "__main__":
    main()
