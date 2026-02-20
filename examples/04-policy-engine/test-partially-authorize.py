#!/usr/bin/env python3
"""
PartiallyAuthorizeActions API 検証スクリプト

このスクリプトは、Gateway + Policy Engine + Cedar Policy の実動作を検証します。

検証内容:
  1. Cognito ユーザーの認証と JWT トークン生成
  2. role=admin での PartiallyAuthorizeActions 呼び出し（全ツールアクセス可能を期待）
  3. role=user での PartiallyAuthorizeActions 呼び出し（特定ツールのみアクセス可能を期待）

前提条件:
  - boto3 >= 1.35.0
  - gateway-config.json が存在する（Gateway ID, Policy Engine ID などを含む）
  - Cognito User Pool にテストユーザーが作成済み
  - Cedar Policy が登録済み（admin_policy, user_policy）

Usage:
  python test-partially-authorize.py
"""

import json
import logging
import os
import sys
from typing import Any

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError as e:
    print(f"[ERROR] Missing dependency: {e}")
    print("Install with: pip install boto3")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "gateway-config.json")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

# テストユーザー情報
# 注意: User Pool は email をユーザー名として使用する設定のため、username = email
TEST_USERS = {
    "admin": {
        "username": "admin-test@example.com",
        "password": "AdminTest123!",
        "role": "admin",
    },
    "user": {
        "username": "user-test@example.com",
        "password": "UserTest123!",
        "role": "user",
    },
}

# テスト対象のアクション（ツール）
TEST_ACTIONS = [
    {
        "actionId": "mcp-target___retrieve_doc",
        "actionDescription": "Retrieve document from MCP server",
        "actionType": "CUSTOM"
    },
    {
        "actionId": "mcp-target___list_tools",
        "actionDescription": "List available tools",
        "actionType": "CUSTOM"
    },
    {
        "actionId": "mcp-target___search_data",
        "actionDescription": "Search data",
        "actionType": "CUSTOM"
    },
]


def load_config() -> dict:
    """gateway-config.json を読み込む。"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"gateway-config.json が見つかりません: {CONFIG_FILE}")
        logger.info("deploy-gateway.py を実行して Gateway をデプロイしてください")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    # 必須フィールドのチェック
    required_fields = ["gatewayId", "cognitoUserPoolId", "cognitoAppClientId"]
    missing = [f for f in required_fields if f not in config]
    if missing:
        logger.error(f"gateway-config.json に必須フィールドがありません: {missing}")
        sys.exit(1)

    return config


def authenticate_user(cognito_client, user_pool_id: str, app_client_id: str, username: str, password: str) -> str:
    """
    Cognito ユーザーを認証し、JWT ID トークンを取得する。

    Returns:
        JWT ID トークン
    """
    logger.info(f"Cognito ユーザー認証: {username}")

    try:
        response = cognito_client.admin_initiate_auth(
            UserPoolId=user_pool_id,
            ClientId=app_client_id,
            AuthFlow="ADMIN_NO_SRP_AUTH",
            AuthParameters={
                "USERNAME": username,
                "PASSWORD": password,
            },
        )

        id_token = response["AuthenticationResult"]["IdToken"]
        logger.info(f"[OK] JWT トークン取得成功")
        return id_token

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "UserNotFoundException":
            logger.error(f"[NG] ユーザーが見つかりません: {username}")
            logger.info("Cognito User Pool でユーザーを作成してください")
        elif error_code == "NotAuthorizedException":
            logger.error(f"[NG] 認証失敗: パスワードが間違っているか、ユーザーが無効です")
        else:
            logger.error(f"[NG] 認証エラー: {error_code} - {error_msg}")

        raise


def test_partially_authorize_actions(
    agentcore_client,
    gateway_id: str,
    id_token: str,
    actions: list[dict],
    role: str
) -> dict[str, Any]:
    """
    PartiallyAuthorizeActions API を呼び出し、アクセス可能なツールを確認する。

    Returns:
        API レスポンス
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"PartiallyAuthorizeActions API 呼び出し (role={role})")
    logger.info(f"{'='*60}")

    try:
        response = agentcore_client.partially_authorize_actions(
            gatewayIdentifier=gateway_id,
            principalAccessToken=id_token,
            actionsToAuthorize=actions,
        )

        logger.info(f"[OK] API 呼び出し成功")

        # 結果の解析
        authorized_actions = response.get("authorizedActions", [])
        unauthorized_actions = response.get("unauthorizedActions", [])

        logger.info(f"\n[許可されたアクション] ({len(authorized_actions)} 件):")
        for action in authorized_actions:
            action_id = action.get("actionId", "unknown")
            logger.info(f"  - {action_id}")

        logger.info(f"\n[拒否されたアクション] ({len(unauthorized_actions)} 件):")
        for action in unauthorized_actions:
            action_id = action.get("actionId", "unknown")
            reason = action.get("reason", "unknown")
            logger.info(f"  - {action_id} (理由: {reason})")

        return {
            "success": True,
            "authorized": authorized_actions,
            "unauthorized": unauthorized_actions,
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"[NG] API 呼び出し失敗: {error_code} - {error_msg}")

        return {
            "success": False,
            "error_code": error_code,
            "error_message": error_msg,
        }


def verify_policy_enforcement(admin_result: dict, user_result: dict) -> bool:
    """
    Cedar Policy が期待通りに動作しているか検証する。

    期待される動作:
      - admin: 全てのアクションが許可される
      - user: 特定のアクション（retrieve_doc, list_tools）のみ許可される

    Returns:
        検証が成功した場合 True
    """
    logger.info(f"\n{'='*60}")
    logger.info("Cedar Policy の動作検証")
    logger.info(f"{'='*60}")

    success = True

    # Admin ロールの検証
    logger.info("\n[Admin ロールの検証]")
    if not admin_result["success"]:
        logger.error("[NG] Admin での API 呼び出しが失敗しました")
        success = False
    else:
        authorized_count = len(admin_result["authorized"])
        if authorized_count == len(TEST_ACTIONS):
            logger.info(f"[OK] Admin は全てのアクション ({authorized_count} 件) にアクセス可能")
        else:
            logger.warning(f"[WARN] Admin は {authorized_count}/{len(TEST_ACTIONS)} 件のアクションにのみアクセス可能")
            logger.warning("Cedar Policy の admin_policy を確認してください")
            success = False

    # User ロールの検証
    logger.info("\n[User ロールの検証]")
    if not user_result["success"]:
        logger.error("[NG] User での API 呼び出しが失敗しました")
        success = False
    else:
        authorized_actions = user_result["authorized"]
        authorized_ids = [a["actionId"] for a in authorized_actions]

        expected_actions = ["mcp-target___retrieve_doc", "mcp-target___list_tools"]

        # 期待されるアクションが許可されているか
        for expected in expected_actions:
            if expected in authorized_ids:
                logger.info(f"[OK] {expected} が許可されています（期待通り）")
            else:
                logger.error(f"[NG] {expected} が拒否されました（期待と異なる）")
                success = False

        # 許可されるべきでないアクションが拒否されているか
        unexpected_actions = [aid for aid in authorized_ids if aid not in expected_actions]
        if unexpected_actions:
            logger.warning(f"[WARN] 予期しないアクションが許可されています: {unexpected_actions}")
            logger.warning("Cedar Policy の user_policy を確認してください")
            success = False
        else:
            logger.info(f"[OK] User は特定のアクション ({len(authorized_actions)} 件) のみアクセス可能")

    return success


def main():
    """メイン処理"""
    logger.info("PartiallyAuthorizeActions API 検証を開始します")

    # 設定ファイルの読み込み
    config = load_config()
    gateway_id = config["gatewayId"]
    user_pool_id = config["cognitoUserPoolId"]
    app_client_id = config["cognitoAppClientId"]

    logger.info(f"\n設定情報:")
    logger.info(f"  Gateway ID: {gateway_id}")
    logger.info(f"  User Pool ID: {user_pool_id}")
    logger.info(f"  App Client ID: {app_client_id}")

    # AWS クライアントの初期化
    cognito_client = boto3.client("cognito-idp", region_name=REGION)
    agentcore_client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # Admin ユーザーの認証とテスト
    try:
        admin_user = TEST_USERS["admin"]
        admin_token = authenticate_user(
            cognito_client,
            user_pool_id,
            app_client_id,
            admin_user["username"],
            admin_user["password"],
        )

        admin_result = test_partially_authorize_actions(
            agentcore_client,
            gateway_id,
            admin_token,
            TEST_ACTIONS,
            "admin",
        )

    except Exception as e:
        logger.error(f"Admin ユーザーのテストに失敗しました: {e}")
        logger.info("\nCognito User Pool でユーザーを作成してください:")
        logger.info(f"  Username: {TEST_USERS['admin']['username']}")
        logger.info(f"  Password: {TEST_USERS['admin']['password']}")
        logger.info(f"  Custom Attribute: role=admin")
        sys.exit(1)

    # User ユーザーの認証とテスト
    try:
        user_user = TEST_USERS["user"]
        user_token = authenticate_user(
            cognito_client,
            user_pool_id,
            app_client_id,
            user_user["username"],
            user_user["password"],
        )

        user_result = test_partially_authorize_actions(
            agentcore_client,
            gateway_id,
            user_token,
            TEST_ACTIONS,
            "user",
        )

    except Exception as e:
        logger.error(f"User ユーザーのテストに失敗しました: {e}")
        logger.info("\nCognito User Pool でユーザーを作成してください:")
        logger.info(f"  Username: {TEST_USERS['user']['username']}")
        logger.info(f"  Password: {TEST_USERS['user']['password']}")
        logger.info(f"  Custom Attribute: role=user")
        sys.exit(1)

    # Cedar Policy の動作検証
    verification_success = verify_policy_enforcement(admin_result, user_result)

    # 結果のサマリー
    logger.info(f"\n{'='*60}")
    logger.info("検証結果サマリー")
    logger.info(f"{'='*60}")

    if verification_success:
        logger.info("[OK] 全ての検証が成功しました")
        logger.info("Cedar Policy が期待通りに動作しています")
        sys.exit(0)
    else:
        logger.error("[NG] 一部の検証が失敗しました")
        logger.error("Cedar Policy の設定を確認してください")
        sys.exit(1)


if __name__ == "__main__":
    main()
