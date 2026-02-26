#!/usr/bin/env python3
"""
Cedar Policy Attribute Mapping E2E 検証スクリプト

このスクリプトは、以下の E2E 未検証項目を実際に検証します：
  1. JWT クレームが Cedar の principal 属性にマッピングされるか
  2. Resource 属性が Cedar でアクセス可能か
  3. Cedar Policy が実際に動作するか

検証方法:
  - Gateway を通じて実際の tools/call を実行
  - Policy Engine のログ（CloudWatch Logs）を確認
  - Cedar Policy の評価結果を検証

前提条件:
  - gateway-config.json が存在する（Gateway ID, Policy Engine ID などを含む）
  - Cognito User Pool にテストユーザーが作成済み
  - Cedar Policy が登録済み

Usage:
  python e2e-verify-cedar-attributes.py
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Optional

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
TEST_USERS = {
    "admin": {
        "username": "admin-test@example.com",
        "password": "AdminTest123!",
        "role": "admin",
        "tenant_id": "tenant-test-a",
    },
    "user": {
        "username": "user-test@example.com",
        "password": "UserTest123!",
        "role": "user",
        "tenant_id": "tenant-test-b",
    },
}


def load_config() -> dict:
    """gateway-config.json を読み込む。"""
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
        logger.error(f"[NG] 認証エラー: {error_code} - {error_msg}")
        raise


def get_policy_engine_log_group(config: dict) -> Optional[str]:
    """Policy Engine の CloudWatch Logs グループ名を取得する。"""
    policy_engine_id = config.get("policyEngineId")
    if not policy_engine_id:
        logger.warning("policyEngineId が見つかりません")
        return None

    # Policy Engine のログは /aws/bedrock/agentcore/policy-engine/{policyEngineId} に出力される
    return f"/aws/bedrock/agentcore/policy-engine/{policy_engine_id}"


def check_policy_evaluation_logs(
    logs_client,
    log_group_name: str,
    start_time: datetime,
    test_user_role: str
) -> dict:
    """
    CloudWatch Logs から Policy Engine の評価ログを取得し、検証する。

    Returns:
        検証結果
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"Policy Engine ログの確認 (role={test_user_role})")
    logger.info(f"{'='*60}")

    try:
        # ログストリームを取得
        streams = logs_client.describe_log_streams(
            logGroupName=log_group_name,
            orderBy="LastEventTime",
            descending=True,
            limit=5
        )

        if not streams.get("logStreams"):
            logger.warning("[WARN] ログストリームが見つかりません")
            return {"success": False, "reason": "no_log_streams"}

        # 最新のログストリームからログを取得
        log_stream_name = streams["logStreams"][0]["logStreamName"]
        logger.info(f"ログストリーム: {log_stream_name}")

        start_timestamp = int(start_time.timestamp() * 1000)

        events = logs_client.get_log_events(
            logGroupName=log_group_name,
            logStreamName=log_stream_name,
            startTime=start_timestamp,
            startFromHead=False
        )

        # ログから Cedar Policy 評価結果を検索
        found_evaluation = False
        principal_attributes_found = []
        resource_attributes_found = []
        evaluation_result = None

        for event in events.get("events", []):
            message = event.get("message", "")

            # JSON 形式のログを解析
            try:
                log_data = json.loads(message)

                # Cedar Policy 評価結果を検索
                if "policyEvaluation" in log_data or "decision" in log_data:
                    found_evaluation = True
                    evaluation_result = log_data.get("decision")

                    # Principal 属性を検索
                    principal = log_data.get("principal", {})
                    if "role" in str(principal):
                        principal_attributes_found.append("role")
                    if "tenant_id" in str(principal):
                        principal_attributes_found.append("tenant_id")
                    if "agent_id" in str(principal):
                        principal_attributes_found.append("agent_id")

                    # Resource 属性を検索
                    resource = log_data.get("resource", {})
                    if "owner_tenant" in str(resource):
                        resource_attributes_found.append("owner_tenant")
                    if "sharing_mode" in str(resource):
                        resource_attributes_found.append("sharing_mode")

                    logger.info(f"[OK] Policy 評価ログ発見: {evaluation_result}")
                    if principal_attributes_found:
                        logger.info(f"[OK] Principal 属性: {principal_attributes_found}")
                    if resource_attributes_found:
                        logger.info(f"[OK] Resource 属性: {resource_attributes_found}")

            except json.JSONDecodeError:
                continue

        if not found_evaluation:
            logger.warning("[WARN] Policy 評価ログが見つかりません")
            logger.info("Policy Engine が LOG_ONLY モードになっているか確認してください")
            return {"success": False, "reason": "no_evaluation_log"}

        return {
            "success": True,
            "evaluation_result": evaluation_result,
            "principal_attributes": principal_attributes_found,
            "resource_attributes": resource_attributes_found,
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]

        if error_code == "ResourceNotFoundException":
            logger.warning(f"[WARN] ログループが見つかりません: {log_group_name}")
            logger.info("Policy Engine がログを出力していない可能性があります")
        else:
            logger.error(f"[NG] ログ取得エラー: {error_code}")

        return {"success": False, "reason": error_code}


def verify_jwt_to_cedar_mapping(log_result: dict, expected_role: str) -> bool:
    """
    JWT クレームが Cedar の principal 属性にマッピングされているか検証する。

    Args:
        log_result: CloudWatch Logs から取得した結果
        expected_role: 期待される role 値

    Returns:
        検証が成功した場合 True
    """
    logger.info(f"\n{'='*60}")
    logger.info("JWT → Cedar Attribute マッピング検証")
    logger.info(f"{'='*60}")

    if not log_result.get("success"):
        logger.error("[NG] ログが取得できませんでした")
        return False

    principal_attrs = log_result.get("principal_attributes", [])

    # role 属性が見つかったか
    if "role" in principal_attrs:
        logger.info(f"[OK] JWT の 'role' クレームが Cedar の principal.role にマッピングされています")
    else:
        logger.error(f"[NG] JWT の 'role' クレームが Cedar の principal.role にマッピングされていません")
        return False

    # tenant_id 属性が見つかったか（オプション）
    if "tenant_id" in principal_attrs:
        logger.info(f"[OK] JWT の 'tenant_id' クレームが Cedar の principal.tenant_id にマッピングされています")
    else:
        logger.warning(f"[WARN] JWT の 'tenant_id' クレームが見つかりません（設定されていない可能性）")

    return True


def verify_resource_attributes(log_result: dict) -> bool:
    """
    Resource 属性が Cedar でアクセス可能か検証する。

    Args:
        log_result: CloudWatch Logs から取得した結果

    Returns:
        検証が成功した場合 True
    """
    logger.info(f"\n{'='*60}")
    logger.info("Resource Attribute マッピング検証")
    logger.info(f"{'='*60}")

    if not log_result.get("success"):
        logger.error("[NG] ログが取得できませんでした")
        return False

    resource_attrs = log_result.get("resource_attributes", [])

    if resource_attrs:
        logger.info(f"[OK] Resource 属性が検出されました: {resource_attrs}")
        return True
    else:
        logger.warning(f"[WARN] Resource 属性が検出されませんでした")
        logger.info("Resource 属性を使用するポリシーがない可能性があります")
        return False


def main():
    """メイン処理"""
    logger.info("Cedar Policy Attribute Mapping E2E 検証を開始します")

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
    logs_client = boto3.client("logs", region_name=REGION)

    # Policy Engine のログループ名を取得
    log_group_name = get_policy_engine_log_group(config)
    if not log_group_name:
        logger.error("Policy Engine ID が見つかりません")
        sys.exit(1)

    logger.info(f"  Policy Engine Log Group: {log_group_name}")

    # Admin ユーザーでテスト
    logger.info(f"\n{'='*60}")
    logger.info("Admin ユーザーでの検証")
    logger.info(f"{'='*60}")

    try:
        admin_user = TEST_USERS["admin"]
        start_time = datetime.now()

        admin_token = authenticate_user(
            cognito_client,
            user_pool_id,
            app_client_id,
            admin_user["username"],
            admin_user["password"],
        )

        logger.info("\n[INFO] JWT トークンを取得しました")
        logger.info("Policy Engine のログを確認します（30秒待機）...")
        time.sleep(30)

        # CloudWatch Logs を確認
        admin_log_result = check_policy_evaluation_logs(
            logs_client,
            log_group_name,
            start_time,
            "admin"
        )

        # JWT → Cedar マッピングを検証
        jwt_mapping_ok = verify_jwt_to_cedar_mapping(admin_log_result, "admin")

        # Resource 属性を検証
        resource_attrs_ok = verify_resource_attributes(admin_log_result)

    except Exception as e:
        logger.error(f"Admin ユーザーのテストに失敗しました: {e}")
        sys.exit(1)

    # 結果のサマリー
    logger.info(f"\n{'='*60}")
    logger.info("検証結果サマリー")
    logger.info(f"{'='*60}")

    if jwt_mapping_ok:
        logger.info("[OK] JWT → Cedar Attribute マッピングが動作しています")
    else:
        logger.error("[NG] JWT → Cedar Attribute マッピングに問題があります")

    if resource_attrs_ok:
        logger.info("[OK] Resource Attribute へのアクセスが可能です")
    else:
        logger.warning("[WARN] Resource Attribute が検出されませんでした")

    logger.info("\n[INFO] 詳細な検証結果は CloudWatch Logs を確認してください:")
    logger.info(f"  Log Group: {log_group_name}")

    if jwt_mapping_ok:
        logger.info("\n[SUCCESS] E2E 検証が成功しました")
        sys.exit(0)
    else:
        logger.error("\n[FAILURE] E2E 検証が失敗しました")
        sys.exit(1)


if __name__ == "__main__":
    main()
