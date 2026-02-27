#!/usr/bin/env python3
"""
Cedar ポリシー登録スクリプト

Policy Engine に Cedar ポリシーを登録します。

Cedar ポリシーの種類:
- admin-policy.cedar: Admin ロールに全ツールを許可
- user-policy.cedar: User ロールに制限されたツールのみ許可

Usage:
  python3 put-cedar-policies.py

  # 特定のポリシーのみ登録
  python3 put-cedar-policies.py --policy admin

  # ポリシーをすべて削除
  python3 put-cedar-policies.py --delete-all
"""

import argparse
import json
import logging
import os
import sys
import time

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("[ERROR] boto3が必要です。pip install boto3を実行してください。")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
POLICY_ENGINE_ID = os.environ.get("POLICY_ENGINE_ID")

# Cedar ポリシー定義
ADMIN_POLICY = """
// Admin ロールは全てのツールにアクセス可能
permit (
    principal is AgentCore::OAuthUser,
    action,
    resource
)
when {
    principal.hasTag("role") &&
    principal.getTag("role") == "admin"
};
"""

USER_POLICY_TEMPLATE = """
// User ロールは制限されたツールのみアクセス可能
permit (
    principal is AgentCore::OAuthUser,
    action in [
        AgentCore::Action::"mcp-target___retrieve_doc",
        AgentCore::Action::"mcp-target___list_tools"
    ],
    resource
)
when {{
    principal.hasTag("role") &&
    principal.getTag("role") == "user"
}};
"""

GUEST_POLICY = """
// Guest ロールは全てのツールへのアクセスを拒否
forbid (
    principal is AgentCore::OAuthUser,
    action,
    resource
)
when {
    principal.hasTag("role") &&
    principal.getTag("role") == "guest"
};
"""


def get_user_policy(gateway_id: str) -> str:
    """
    User ポリシーを生成する

    Note: Gateway ARN をハードコードせず、動的に生成するバージョン
    """
    # Gateway ARN を構築（リージョンとアカウントIDは実行時に取得）
    sts = boto3.client("sts", region_name=REGION)
    account_id = sts.get_caller_identity()["Account"]

    # Note: resource制約をコメントアウト（Gateway ARN のハードコードを避けるため）
    user_policy = f"""
// User ロールは制限されたツールのみアクセス可能
permit (
    principal is AgentCore::OAuthUser,
    action in [
        AgentCore::Action::"mcp-target___retrieve_doc",
        AgentCore::Action::"mcp-target___list_tools"
    ],
    resource
)
when {{
    principal.hasTag("role") &&
    principal.getTag("role") == "user"
}};
"""
    return user_policy


def list_existing_policies(client) -> list:
    """既存のポリシーを一覧取得する"""
    try:
        response = client.list_policy_store_entries(
            policyEngineId=POLICY_ENGINE_ID,
            maxResults=100
        )
        entries = response.get("policyStoreEntries", [])
        logger.info("既存のポリシー数: %d", len(entries))
        for entry in entries:
            logger.info("  - %s (ID: %s)", entry.get("description", "No description"), entry.get("policyId"))
        return entries
    except ClientError as e:
        logger.error("ポリシー一覧の取得に失敗: %s", e)
        return []


def put_policy(client, policy_text: str, description: str) -> bool:
    """
    Cedar ポリシーを登録する

    Args:
        policy_text: Cedar ポリシーのテキスト
        description: ポリシーの説明
    """
    logger.info("=" * 80)
    logger.info("Cedar ポリシーを登録します")
    logger.info("=" * 80)
    logger.info("  Policy Engine ID: %s", POLICY_ENGINE_ID)
    logger.info("  Description: %s", description)
    logger.info("\nPolicy Content:")
    logger.info("-" * 80)
    logger.info(policy_text)
    logger.info("-" * 80)

    try:
        response = client.create_policy_store_entry(
            policyEngineId=POLICY_ENGINE_ID,
            description=description,
            policyText=policy_text
        )

        policy_id = response.get("policyId")
        logger.info("\n[SUCCESS] ポリシーを登録しました")
        logger.info("  Policy ID: %s", policy_id)
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "ValidationException":
            logger.error("[ERROR] Cedar ポリシーの構文エラー: %s", error_msg)
        elif error_code == "ConflictException":
            logger.info("[INFO] 同じポリシーが既に登録されています")
            return True
        else:
            logger.error("[ERROR] ポリシーの登録に失敗: %s - %s", error_code, error_msg)

        return False


def delete_policy(client, policy_id: str) -> bool:
    """ポリシーを削除する"""
    try:
        client.delete_policy_store_entry(
            policyEngineId=POLICY_ENGINE_ID,
            policyId=policy_id
        )
        logger.info("[OK] ポリシーを削除しました: %s", policy_id)
        return True
    except ClientError as e:
        logger.error("[ERROR] ポリシー削除に失敗: %s", e)
        return False


def delete_all_policies(client):
    """全てのポリシーを削除する"""
    logger.info("=" * 80)
    logger.info("全てのポリシーを削除します")
    logger.info("=" * 80)

    entries = list_existing_policies(client)
    if not entries:
        logger.info("削除するポリシーがありません")
        return

    for entry in entries:
        policy_id = entry.get("policyId")
        description = entry.get("description", "No description")
        logger.info("削除中: %s (ID: %s)", description, policy_id)
        delete_policy(client, policy_id)
        time.sleep(0.5)

    logger.info("\n[OK] 全てのポリシーを削除しました")


def validate_environment():
    """環境変数のバリデーション"""
    if not POLICY_ENGINE_ID:
        logger.error("環境変数 POLICY_ENGINE_ID が設定されていません")
        logger.info("Hint: export POLICY_ENGINE_ID=$(python3 create-policy-engine.py --get-id)")
        return False

    logger.info("環境変数の検証: OK")
    logger.info("  POLICY_ENGINE_ID: %s", POLICY_ENGINE_ID)
    logger.info("  REGION: %s", REGION)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Cedar ポリシーを Policy Engine に登録する"
    )
    parser.add_argument(
        "--policy",
        choices=["admin", "user", "guest", "all"],
        default="all",
        help="登録するポリシーを指定"
    )
    parser.add_argument(
        "--delete-all",
        action="store_true",
        help="全てのポリシーを削除"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="既存のポリシーを一覧表示"
    )
    parser.add_argument(
        "--gateway-id",
        help="Gateway ID（User ポリシーで使用）"
    )

    args = parser.parse_args()

    # 環境変数の検証
    if not validate_environment():
        sys.exit(1)

    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # --list オプション
    if args.list:
        logger.info("=" * 80)
        logger.info("既存のポリシー一覧")
        logger.info("=" * 80)
        list_existing_policies(client)
        sys.exit(0)

    # --delete-all オプション
    if args.delete_all:
        confirm = input("全てのポリシーを削除しますか？ (yes/no): ")
        if confirm.lower() == "yes":
            delete_all_policies(client)
            sys.exit(0)
        else:
            logger.info("キャンセルしました")
            sys.exit(0)

    # Gateway ID の取得
    gateway_id = args.gateway_id or os.environ.get("GATEWAY_ID")

    # ポリシー登録
    success_count = 0
    total_count = 0

    policies_to_register = []
    if args.policy in ["admin", "all"]:
        policies_to_register.append(("Admin Policy", ADMIN_POLICY))

    if args.policy in ["user", "all"]:
        if gateway_id:
            user_policy = get_user_policy(gateway_id)
            policies_to_register.append(("User Policy", user_policy))
        else:
            logger.warning("Gateway ID が指定されていません。User ポリシーはスキップします。")
            logger.info("Hint: export GATEWAY_ID=xxx または --gateway-id オプションを使用")

    if args.policy in ["guest", "all"]:
        policies_to_register.append(("Guest Policy (forbid)", GUEST_POLICY))

    for description, policy_text in policies_to_register:
        total_count += 1
        if put_policy(client, policy_text, description):
            success_count += 1
        time.sleep(1)

    # 結果サマリー
    logger.info("\n" + "=" * 80)
    logger.info("ポリシー登録完了")
    logger.info("=" * 80)
    logger.info("  登録成功: %d / %d", success_count, total_count)

    # 登録されたポリシーを確認
    logger.info("\n登録されているポリシー:")
    list_existing_policies(client)

    logger.info("\n次のステップ:")
    logger.info("  1. 検証実行: python3 test-phase3.py")
    logger.info("  2. Policy Engine モード変更: python3 create-policy-engine.py --update-mode ENFORCE")

    sys.exit(0 if success_count == total_count else 1)


if __name__ == "__main__":
    main()
