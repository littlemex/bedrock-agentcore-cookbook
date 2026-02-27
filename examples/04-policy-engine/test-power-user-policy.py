#!/usr/bin/env python3
"""
Power-user ロール Cedar ポリシー検証スクリプト

このスクリプトは、Power-user ロールの Cedar ポリシーが期待通りに動作するかを検証する。

検証内容:
  1. Power-user が許可されたツール（read_file, list_directory, brave_web_search）にアクセス可能
  2. Power-user が拒否されたツール（delete_file）にアクセス不可
  3. Power-user が許可リスト外のツール（search_data）にアクセス不可

前提条件:
  - Gateway がデプロイ済み
  - Policy Engine が Gateway に関連付け済み（ENFORCE モード推奨）
  - Cedar ポリシーが登録済み（power-user-policy.cedar を含む）
  - Cognito User Pool に power-user テストユーザーが作成済み
  - gateway-config.json が存在する

Usage:
  python3 test-power-user-policy.py

環境変数:
  AWS_DEFAULT_REGION: AWS リージョン（デフォルト: us-east-1）
"""

import json
import logging
import os
import sys
from typing import Any

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("[ERROR] boto3 が必要です。pip install boto3 を実行してください。")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "gateway-config.json")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

# Power-user テストユーザー情報
POWER_USER = {
    "username": "power-user-test@example.com",
    "password": "PowerUserTest123!",
    "role": "power-user",
}

# テスト対象のアクション（ツール）
# Power-user に許可されるべきツール
ALLOWED_ACTIONS = [
    {
        "actionId": "mcp-target___read_file",
        "actionDescription": "Read file content",
        "actionType": "CUSTOM",
    },
    {
        "actionId": "mcp-target___list_directory",
        "actionDescription": "List directory contents",
        "actionType": "CUSTOM",
    },
    {
        "actionId": "mcp-target___brave_web_search",
        "actionDescription": "Web search via Brave",
        "actionType": "CUSTOM",
    },
]

# Power-user に拒否されるべきツール
DENIED_ACTIONS = [
    {
        "actionId": "mcp-target___delete_file",
        "actionDescription": "Delete file (explicitly forbidden)",
        "actionType": "CUSTOM",
    },
]

# Power-user の許可リスト外のツール（暗黙的に拒否）
UNLISTED_ACTIONS = [
    {
        "actionId": "mcp-target___search_data",
        "actionDescription": "Search data (not in power-user permit list)",
        "actionType": "CUSTOM",
    },
]

# テスト結果
test_results = {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "tests": [],
}


def load_config() -> dict:
    """gateway-config.json を読み込む"""
    if not os.path.exists(CONFIG_FILE):
        logger.error("gateway-config.json が見つかりません: %s", CONFIG_FILE)
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    required_fields = ["gatewayId", "cognitoUserPoolId", "cognitoAppClientId"]
    missing = [f for f in required_fields if f not in config]
    if missing:
        logger.error("gateway-config.json に必須フィールドがありません: %s", missing)
        sys.exit(1)

    return config


def authenticate_user(
    cognito_client, user_pool_id: str, app_client_id: str, username: str, password: str
) -> str:
    """Cognito ユーザーを認証し、JWT ID トークンを取得する"""
    logger.info("Cognito ユーザー認証: %s", username)

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
        logger.info("[OK] JWT トークン取得成功: %s...", id_token[:50])
        return id_token

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "UserNotFoundException":
            logger.error("[NG] ユーザーが見つかりません: %s", username)
            logger.info("Cognito User Pool で power-user テストユーザーを作成してください")
            logger.info("  Username: %s", username)
            logger.info("  Custom Attribute: role=power-user")
        elif error_code == "NotAuthorizedException":
            logger.error("[NG] 認証失敗: パスワードが間違っているか、ユーザーが無効です")
        else:
            logger.error("[NG] 認証エラー: %s - %s", error_code, error_msg)

        raise


def record_test(test_name: str, passed: bool, details: str = ""):
    """テスト結果を記録する"""
    test_results["total"] += 1
    if passed:
        test_results["passed"] += 1
        status = "[PASS]"
    else:
        test_results["failed"] += 1
        status = "[FAIL]"

    test_results["tests"].append(
        {"name": test_name, "passed": passed, "details": details}
    )

    logger.info("  %s %s", status, test_name)
    if details:
        logger.info("       %s", details)


def test_partially_authorize(
    agentcore_client,
    gateway_id: str,
    id_token: str,
    actions: list[dict],
) -> dict[str, Any]:
    """PartiallyAuthorizeActions API を呼び出す"""
    try:
        response = agentcore_client.partially_authorize_actions(
            gatewayIdentifier=gateway_id,
            principalAccessToken=id_token,
            actionsToAuthorize=actions,
        )

        authorized_actions = response.get("authorizedActions", [])
        unauthorized_actions = response.get("unauthorizedActions", [])

        return {
            "success": True,
            "authorized": authorized_actions,
            "unauthorized": unauthorized_actions,
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error("[NG] API 呼び出し失敗: %s - %s", error_code, error_msg)

        return {
            "success": False,
            "error_code": error_code,
            "error_message": error_msg,
        }


def test_1_allowed_tools(agentcore_client, gateway_id: str, id_token: str):
    """
    Test 1: Power-user が許可されたツールにアクセスできることを検証

    対象: read_file, list_directory, brave_web_search
    """
    logger.info("=" * 80)
    logger.info("[Test 1] Power-user: 許可ツールへのアクセス検証")
    logger.info("=" * 80)

    result = test_partially_authorize(
        agentcore_client, gateway_id, id_token, ALLOWED_ACTIONS
    )

    if not result["success"]:
        record_test(
            "1-1. PartiallyAuthorizeActions API 呼び出し",
            False,
            "API 呼び出しに失敗",
        )
        return

    authorized_ids = [a["actionId"] for a in result["authorized"]]

    for action in ALLOWED_ACTIONS:
        action_id = action["actionId"]
        tool_name = action_id.replace("mcp-target___", "")
        is_authorized = action_id in authorized_ids
        record_test(
            f"1. Power-user: {tool_name} が許可されている",
            is_authorized,
            f"Expected: ALLOW, Got: {'ALLOW' if is_authorized else 'DENY'}",
        )


def test_2_denied_tools(agentcore_client, gateway_id: str, id_token: str):
    """
    Test 2: Power-user が明示的に拒否されたツールにアクセスできないことを検証

    対象: delete_file (forbid ルールで明示的に拒否)
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 2] Power-user: 明示的拒否ツールのアクセス検証")
    logger.info("=" * 80)

    result = test_partially_authorize(
        agentcore_client, gateway_id, id_token, DENIED_ACTIONS
    )

    if not result["success"]:
        record_test(
            "2-1. PartiallyAuthorizeActions API 呼び出し",
            False,
            "API 呼び出しに失敗",
        )
        return

    unauthorized_ids = [a["actionId"] for a in result["unauthorized"]]

    for action in DENIED_ACTIONS:
        action_id = action["actionId"]
        tool_name = action_id.replace("mcp-target___", "")
        is_denied = action_id in unauthorized_ids
        record_test(
            f"2. Power-user: {tool_name} が拒否されている",
            is_denied,
            f"Expected: DENY, Got: {'DENY' if is_denied else 'ALLOW'}",
        )


def test_3_unlisted_tools(agentcore_client, gateway_id: str, id_token: str):
    """
    Test 3: Power-user が許可リスト外のツールにアクセスできないことを検証

    対象: search_data (permit リストに含まれない = 暗黙的拒否)
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 3] Power-user: 許可リスト外ツールのアクセス検証")
    logger.info("=" * 80)

    result = test_partially_authorize(
        agentcore_client, gateway_id, id_token, UNLISTED_ACTIONS
    )

    if not result["success"]:
        record_test(
            "3-1. PartiallyAuthorizeActions API 呼び出し",
            False,
            "API 呼び出しに失敗",
        )
        return

    unauthorized_ids = [a["actionId"] for a in result["unauthorized"]]

    for action in UNLISTED_ACTIONS:
        action_id = action["actionId"]
        tool_name = action_id.replace("mcp-target___", "")
        is_denied = action_id in unauthorized_ids
        record_test(
            f"3. Power-user: {tool_name} が暗黙的に拒否されている",
            is_denied,
            f"Expected: DENY (implicit), Got: {'DENY' if is_denied else 'ALLOW'}",
        )


def print_summary():
    """テスト結果のサマリーを出力する"""
    logger.info("\n" + "=" * 80)
    logger.info("Test Summary")
    logger.info("=" * 80)
    logger.info("Total Tests: %d", test_results["total"])
    logger.info("Passed: %d", test_results["passed"])
    logger.info("Failed: %d", test_results["failed"])
    logger.info("=" * 80)

    if test_results["failed"] > 0:
        logger.info("\nFailed Tests:")
        for test in test_results["tests"]:
            if not test["passed"]:
                logger.info("  - %s", test["name"])
                if test["details"]:
                    logger.info("    %s", test["details"])

    if test_results["failed"] == 0:
        logger.info("\n[SUCCESS] All tests passed!")
    else:
        logger.info("\n[FAILURE] Some tests failed.")


def main():
    logger.info("=" * 80)
    logger.info("Power-user ロール Cedar ポリシー検証")
    logger.info("=" * 80)
    logger.info("Region: %s", REGION)

    # 設定ファイルを読み込む
    config = load_config()
    gateway_id = config["gatewayId"]
    user_pool_id = config["cognitoUserPoolId"]
    app_client_id = config["cognitoAppClientId"]

    logger.info("\n設定情報:")
    logger.info("  Gateway ID: %s", gateway_id)
    logger.info("  User Pool ID: %s", user_pool_id)
    logger.info("  App Client ID: %s", app_client_id)

    # AWS クライアントを作成
    cognito_client = boto3.client("cognito-idp", region_name=REGION)
    agentcore_client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    try:
        # Power-user の JWT トークンを取得
        id_token = authenticate_user(
            cognito_client,
            user_pool_id,
            app_client_id,
            POWER_USER["username"],
            POWER_USER["password"],
        )

        # Test 1: 許可ツールへのアクセス検証
        test_1_allowed_tools(agentcore_client, gateway_id, id_token)

        # Test 2: 明示的拒否ツールのアクセス検証
        test_2_denied_tools(agentcore_client, gateway_id, id_token)

        # Test 3: 許可リスト外ツールのアクセス検証
        test_3_unlisted_tools(agentcore_client, gateway_id, id_token)

        # テスト結果のサマリーを出力
        print_summary()

        sys.exit(0 if test_results["failed"] == 0 else 1)

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        logger.error("[ERROR] AWS API エラー: %s", error_code)
        logger.info("\nPower-user テストユーザーの作成手順:")
        logger.info("  1. Cognito User Pool にユーザーを追加")
        logger.info("     Username: %s", POWER_USER["username"])
        logger.info("     Password: %s", POWER_USER["password"])
        logger.info("     Custom Attribute: role=power-user")
        logger.info("  2. setup-cognito-users.py を参考にしてください")
        sys.exit(1)

    except Exception as e:
        logger.error("[ERROR] 予期しないエラーが発生しました: %s", e)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
