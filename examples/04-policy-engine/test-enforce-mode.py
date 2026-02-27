#!/usr/bin/env python3
"""
Policy Engine ENFORCE Mode E2E検証スクリプト

このスクリプトは以下を検証する:
1. LOG_ONLY モード: 全アクセスが許可される（ポリシー評価はログのみ）
2. ENFORCE モードへの切り替え
3. ENFORCE モード: Cedar Policy に基づいて実際にアクセス制御が行われる
   - role=admin: 全ツールへのアクセスが許可される
   - role=user: 制限されたツールのみアクセス可能
   - ポリシーにマッチしないリクエストは拒否される

前提条件:
- Gateway がデプロイ済み
- Policy Engine が Gateway に関連付け済み（LOG_ONLY モード）
- Cedar ポリシーが登録済み（admin-policy.cedar, user-policy.cedar）
- Cognito User Pool とテストユーザーが作成済み
- gateway-config.json が存在する

Usage:
  python3 test-enforce-mode.py

環境変数:
  AWS_DEFAULT_REGION: AWS リージョン（デフォルト: us-east-1）
"""

import json
import logging
import os
import sys
import time
from typing import Dict, Any, Optional

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

# テスト結果
test_results = {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "tests": []
}


def load_config() -> dict:
    """gateway-config.json を読み込む"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"gateway-config.json が見つかりません: {CONFIG_FILE}")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    required_fields = ["gatewayId", "cognitoUserPoolId", "cognitoAppClientId"]
    missing = [f for f in required_fields if f not in config]
    if missing:
        logger.error(f"gateway-config.json に必須フィールドがありません: {missing}")
        sys.exit(1)

    return config


def get_jwt_token(cognito_client, user_pool_id: str, client_id: str, username: str, password: str) -> Optional[str]:
    """
    Cognito User Pool からユーザー認証して JWT トークンを取得する

    Returns:
        str: ID Token (JWT)
    """
    try:
        response = cognito_client.admin_initiate_auth(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            AuthFlow="ADMIN_NO_SRP_AUTH",
            AuthParameters={
                "USERNAME": username,
                "PASSWORD": password,
            }
        )

        id_token = response["AuthenticationResult"]["IdToken"]
        logger.info("  JWT トークン取得成功: %s...", id_token[:50])
        return id_token

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        logger.error("  JWT トークン取得失敗: %s", error_code)
        return None


def invoke_gateway_tools_list(gateway_runtime_client, gateway_id: str, jwt_token: str) -> Dict[str, Any]:
    """
    Gateway 経由で tools/list を呼び出す

    Args:
        jwt_token: JWT トークン

    Returns:
        dict: API レスポンス
    """
    headers = {"Authorization": f"Bearer {jwt_token}"}

    try:
        response = gateway_runtime_client.invoke_gateway(
            gatewayIdentifier=gateway_id,
            targetName="mcp-target",  # ターゲット名
            headers=headers,
            body={
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 1
            }
        )

        return {
            "status_code": response.get("statusCode", 200),
            "body": response.get("body", {}),
            "success": True
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        return {
            "status_code": 403 if error_code == "AccessDeniedException" else 500,
            "error": f"{error_code}: {error_msg}",
            "success": False
        }


def invoke_gateway_tool_call(gateway_runtime_client, gateway_id: str, jwt_token: str, tool_name: str) -> Dict[str, Any]:
    """
    Gateway 経由で tools/call を呼び出す

    Args:
        jwt_token: JWT トークン
        tool_name: ツール名

    Returns:
        dict: API レスポンス
    """
    headers = {"Authorization": f"Bearer {jwt_token}"}

    try:
        response = gateway_runtime_client.invoke_gateway(
            gatewayIdentifier=gateway_id,
            targetName="mcp-target",
            headers=headers,
            body={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {}
                },
                "id": 1
            }
        )

        return {
            "status_code": response.get("statusCode", 200),
            "body": response.get("body", {}),
            "success": True
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        return {
            "status_code": 403 if error_code == "AccessDeniedException" else 500,
            "error": f"{error_code}: {error_msg}",
            "success": False
        }


def get_current_mode(client, gateway_id: str) -> str:
    """Gateway に関連付けられた Policy Engine の現在のモードを取得する"""
    try:
        response = client.get_gateway(gatewayIdentifier=gateway_id)
        policy_engine_config = response.get("policyEngineConfiguration", {})
        return policy_engine_config.get("mode")
    except ClientError as e:
        logger.error(f"Gateway 情報の取得に失敗: {e}")
        return None


def update_mode(client, config: dict, new_mode: str) -> bool:
    """Policy Engine のモードを変更する"""
    gateway_id = config["gatewayId"]
    policy_engine_arn = config["policyEngineArn"]

    try:
        # Gateway の現在の設定を取得
        response = client.get_gateway(gatewayIdentifier=gateway_id)

        # 不要なフィールドを削除
        response.pop("ResponseMetadata", None)
        response.pop("updatedAt", None)
        response.pop("createdAt", None)
        response.pop("gatewayUrl", None)
        response.pop("status", None)
        response.pop("workloadIdentityDetails", None)
        response.pop("gatewayArn", None)
        response.pop("gatewayId", None)

        # update_gateway のパラメータを構築
        update_params = {
            "gatewayIdentifier": gateway_id,
            "name": response.get("name"),
            "roleArn": response.get("roleArn"),
            "protocolType": response.get("protocolType"),
            "authorizerType": response.get("authorizerType"),
            "authorizerConfiguration": response.get("authorizerConfiguration"),
            "policyEngineConfiguration": {
                "arn": policy_engine_arn,
                "mode": new_mode
            }
        }

        # 任意のフィールドを追加
        if response.get("protocolConfiguration"):
            update_params["protocolConfiguration"] = response["protocolConfiguration"]
        if response.get("interceptorConfigurations"):
            update_params["interceptorConfigurations"] = response["interceptorConfigurations"]

        # Gateway を更新
        client.update_gateway(**update_params)
        logger.info(f"  [OK] モードを {new_mode} に変更しました")
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"  [ERROR] モード変更に失敗: {error_code} - {error_msg}")
        return False


def record_test(test_name: str, passed: bool, details: str = ""):
    """テスト結果を記録する"""
    test_results["total"] += 1
    if passed:
        test_results["passed"] += 1
        status = "[PASS]"
    else:
        test_results["failed"] += 1
        status = "[FAIL]"

    test_results["tests"].append({
        "name": test_name,
        "passed": passed,
        "details": details
    })

    logger.info(f"  {status} {test_name}")
    if details:
        logger.info(f"       {details}")


def test_1_log_only_mode(gateway_runtime_client, cognito_client, config: dict):
    """
    Test 1: LOG_ONLY モードでの動作確認

    LOG_ONLY モードでは、ポリシー評価がログに記録されるが、
    アクセスは全て許可される。
    """
    logger.info("=" * 80)
    logger.info("[Test 1] LOG_ONLY モード: 全アクセスが許可される")
    logger.info("=" * 80)

    gateway_id = config["gatewayId"]
    user_pool_id = config["cognitoUserPoolId"]
    client_id = config["cognitoAppClientId"]

    # admin ユーザーの JWT トークンを取得
    logger.info("\n1-1. Admin ユーザーで tools/list を呼び出す（LOG_ONLY）")
    admin_token = get_jwt_token(cognito_client, user_pool_id, client_id, "admin-test@example.com", "AdminTest123!")
    if not admin_token:
        record_test("1-1. Admin ユーザー JWT 取得", False, "JWT トークンの取得に失敗")
        return

    response = invoke_gateway_tools_list(gateway_runtime_client, gateway_id, admin_token)
    record_test(
        "1-1. LOG_ONLY: Admin ユーザー tools/list",
        response["success"],
        f"Expected: Success, Got: {response['success']}"
    )

    # user ユーザーの JWT トークンを取得
    logger.info("\n1-2. User ユーザーで tools/list を呼び出す（LOG_ONLY）")
    user_token = get_jwt_token(cognito_client, user_pool_id, client_id, "user-test@example.com", "UserTest123!")
    if not user_token:
        record_test("1-2. User ユーザー JWT 取得", False, "JWT トークンの取得に失敗")
        return

    response = invoke_gateway_tools_list(gateway_runtime_client, gateway_id, user_token)
    record_test(
        "1-2. LOG_ONLY: User ユーザー tools/list",
        response["success"],
        f"Expected: Success, Got: {response['success']}"
    )

    logger.info("\n[結論] LOG_ONLY モードでは、ポリシーに関係なく全アクセスが許可される")


def test_2_switch_to_enforce_mode(control_client, config: dict):
    """
    Test 2: ENFORCE モードへの切り替え
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 2] ENFORCE モードへの切り替え")
    logger.info("=" * 80)

    gateway_id = config["gatewayId"]

    # 現在のモードを確認
    logger.info("\n2-1. 現在のモードを確認")
    current_mode = get_current_mode(control_client, gateway_id)
    logger.info(f"  Current Mode: {current_mode}")

    # ENFORCE モードに切り替え
    logger.info("\n2-2. ENFORCE モードに切り替え")
    success = update_mode(control_client, config, "ENFORCE")
    record_test(
        "2-2. ENFORCE モードへの切り替え",
        success,
        "Policy Engine モードを ENFORCE に変更"
    )

    # 切り替え後のモードを確認
    time.sleep(2)
    new_mode = get_current_mode(control_client, gateway_id)
    logger.info(f"  New Mode: {new_mode}")

    if new_mode != "ENFORCE":
        record_test("2-3. モード切り替え確認", False, f"Expected: ENFORCE, Got: {new_mode}")
    else:
        record_test("2-3. モード切り替え確認", True, "ENFORCE モードへの切り替えが完了")


def test_3_enforce_mode_access_control(gateway_runtime_client, cognito_client, config: dict):
    """
    Test 3: ENFORCE モードでのアクセス制御

    Cedar Policy に基づいて実際にアクセス制御が行われる:
    - role=admin: 全ツールへのアクセスが許可される
    - role=user: 制限されたツールのみアクセス可能
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 3] ENFORCE モード: Cedar Policy に基づくアクセス制御")
    logger.info("=" * 80)

    gateway_id = config["gatewayId"]
    user_pool_id = config["cognitoUserPoolId"]
    client_id = config["cognitoAppClientId"]

    # admin ユーザーの JWT トークンを取得
    logger.info("\n3-1. Admin ユーザーで tools/list を呼び出す（ENFORCE）")
    admin_token = get_jwt_token(cognito_client, user_pool_id, client_id, "admin-test@example.com", "AdminTest123!")
    if not admin_token:
        record_test("3-1. Admin ユーザー JWT 取得", False, "JWT トークンの取得に失敗")
        return

    response = invoke_gateway_tools_list(gateway_runtime_client, gateway_id, admin_token)
    record_test(
        "3-1. ENFORCE: Admin ユーザー tools/list",
        response["success"],
        f"Expected: Success (全ツールアクセス可能), Got: {response['success']}"
    )

    # user ユーザーの JWT トークンを取得
    logger.info("\n3-2. User ユーザーで tools/list を呼び出す（ENFORCE）")
    user_token = get_jwt_token(cognito_client, user_pool_id, client_id, "user-test@example.com", "UserTest123!")
    if not user_token:
        record_test("3-2. User ユーザー JWT 取得", False, "JWT トークンの取得に失敗")
        return

    response = invoke_gateway_tools_list(gateway_runtime_client, gateway_id, user_token)
    # User ポリシーで list_tools アクションが許可されているため、success になるべき
    record_test(
        "3-2. ENFORCE: User ユーザー tools/list",
        response["success"],
        f"Expected: Success (list_tools は許可), Got: {response['success']}"
    )

    # user ユーザーで許可されていないツールを呼び出す
    logger.info("\n3-3. User ユーザーで許可されていないツールを呼び出す（ENFORCE）")
    response = invoke_gateway_tool_call(gateway_runtime_client, gateway_id, user_token, "unauthorized_tool")
    # User ポリシーで unauthorized_tool は許可されていないため、AccessDenied になるべき
    record_test(
        "3-3. ENFORCE: User ユーザー unauthorized_tool",
        not response["success"] and response["status_code"] == 403,
        f"Expected: AccessDenied (403), Got: {response['status_code']}"
    )

    logger.info("\n[結論] ENFORCE モードでは、Cedar Policy に基づいて実際にアクセス制御が行われる")


def test_4_restore_log_only_mode(control_client, config: dict):
    """
    Test 4: LOG_ONLY モードに戻す（クリーンアップ）
    """
    logger.info("\n" + "=" * 80)
    logger.info("[Test 4] LOG_ONLY モードに戻す（クリーンアップ）")
    logger.info("=" * 80)

    gateway_id = config["gatewayId"]

    # LOG_ONLY モードに戻す
    logger.info("\n4-1. LOG_ONLY モードに戻す")
    success = update_mode(control_client, config, "LOG_ONLY")
    record_test(
        "4-1. LOG_ONLY モードへの復元",
        success,
        "Policy Engine モードを LOG_ONLY に復元"
    )

    # 復元後のモードを確認
    time.sleep(2)
    new_mode = get_current_mode(control_client, gateway_id)
    logger.info(f"  Restored Mode: {new_mode}")

    if new_mode != "LOG_ONLY":
        record_test("4-2. モード復元確認", False, f"Expected: LOG_ONLY, Got: {new_mode}")
    else:
        record_test("4-2. モード復元確認", True, "LOG_ONLY モードへの復元が完了")


def print_summary():
    """テスト結果のサマリーを出力する"""
    logger.info("\n" + "=" * 80)
    logger.info("Test Summary")
    logger.info("=" * 80)
    logger.info(f"Total Tests: {test_results['total']}")
    logger.info(f"Passed: {test_results['passed']}")
    logger.info(f"Failed: {test_results['failed']}")
    logger.info("=" * 80)

    if test_results["failed"] > 0:
        logger.info("\nFailed Tests:")
        for test in test_results["tests"]:
            if not test["passed"]:
                logger.info(f"  - {test['name']}")
                if test["details"]:
                    logger.info(f"    {test['details']}")

    if test_results["failed"] == 0:
        logger.info("\n[SUCCESS] All tests passed!")
    else:
        logger.info("\n[FAILURE] Some tests failed.")


def main():
    logger.info("=" * 80)
    logger.info("Policy Engine ENFORCE Mode E2E 検証")
    logger.info("=" * 80)
    logger.info(f"Region: {REGION}")

    # 設定ファイルを読み込む
    config = load_config()

    # AWS クライアントを作成
    control_client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    gateway_runtime_client = boto3.client("bedrock-agentcore-runtime", region_name=REGION)
    cognito_client = boto3.client("cognito-idp", region_name=REGION)

    try:
        # Test 1: LOG_ONLY モードでの動作確認
        test_1_log_only_mode(gateway_runtime_client, cognito_client, config)

        # Test 2: ENFORCE モードへの切り替え
        test_2_switch_to_enforce_mode(control_client, config)

        # Test 3: ENFORCE モードでのアクセス制御
        test_3_enforce_mode_access_control(gateway_runtime_client, cognito_client, config)

        # Test 4: LOG_ONLY モードに戻す（クリーンアップ）
        test_4_restore_log_only_mode(control_client, config)

        # テスト結果のサマリーを出力
        print_summary()

        sys.exit(0 if test_results["failed"] == 0 else 1)

    except Exception as e:
        logger.error(f"[ERROR] 予期しないエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
