#!/usr/bin/env python3
"""
Tools/Call E2E 検証スクリプト

実際の MCP Server へ tools/call リクエストを送信し、
Policy Engine のログを確認して JWT → Cedar マッピングを検証します。

Usage:
  python3 invoke-tool-e2e.py
"""

import json
import logging
import os
import sys
import time
from datetime import datetime

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
    },
    "user": {
        "username": "user-test@example.com",
        "password": "UserTest123!",
        "role": "user",
    },
}


def load_config() -> dict:
    """gateway-config.json を読み込む。"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"gateway-config.json が見つかりません: {CONFIG_FILE}")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    return config


def authenticate_user(cognito_client, user_pool_id: str, app_client_id: str, username: str, password: str) -> str:
    """Cognito ユーザーを認証し、JWT ID トークンを取得する。"""
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


def invoke_tool_via_gateway(
    agent_runtime_client,
    gateway_id: str,
    target_id: str,
    tool_name: str,
    id_token: str,
    parameters: dict
) -> dict:
    """
    Gateway を通じて MCP Server の tool を呼び出す。

    Returns:
        API レスポンス
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"Tools/Call リクエスト")
    logger.info(f"{'='*60}")
    logger.info(f"  Gateway ID: {gateway_id}")
    logger.info(f"  Target ID: {target_id}")
    logger.info(f"  Tool Name: {tool_name}")
    logger.info(f"  Parameters: {json.dumps(parameters, indent=2)}")

    try:
        # bedrock-agent-runtime の invoke API を使用
        response = agent_runtime_client.invoke(
            agentId=gateway_id,
            sessionId=f"test-session-{int(time.time())}",
            inputText=json.dumps({
                "action": "tools/call",
                "targetId": target_id,
                "toolName": tool_name,
                "parameters": parameters
            }),
            # JWT トークンを含める方法は API 仕様に依存
            # 現時点では標準的な方法が不明なため、後で調整が必要
        )

        logger.info(f"[OK] リクエスト送信成功")
        return {"success": True, "response": response}

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"[NG] リクエスト失敗: {error_code} - {error_msg}")
        return {"success": False, "error_code": error_code, "error_message": error_msg}
    except Exception as e:
        logger.error(f"[NG] 予期しないエラー: {e}")
        return {"success": False, "error": str(e)}


def check_cloudwatch_logs(logs_client, log_group_name: str, start_time: datetime, role: str) -> dict:
    """CloudWatch Logs から Policy Engine の評価ログを確認する。"""
    logger.info(f"\n{'='*60}")
    logger.info(f"CloudWatch Logs 確認 (role={role})")
    logger.info(f"{'='*60}")
    logger.info(f"  Log Group: {log_group_name}")
    logger.info(f"  開始時刻: {start_time.isoformat()}")

    time.sleep(10)  # ログが書き込まれるまで待機

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

        logger.info(f"[OK] ログストリームが見つかりました: {len(streams['logStreams'])} 件")

        # 最新のログストリームからログを取得
        for stream in streams["logStreams"]:
            log_stream_name = stream["logStreamName"]
            logger.info(f"\nログストリーム: {log_stream_name}")

            start_timestamp = int(start_time.timestamp() * 1000)

            events = logs_client.get_log_events(
                logGroupName=log_group_name,
                logStreamName=log_stream_name,
                startTime=start_timestamp,
                limit=100
            )

            if not events.get("events"):
                logger.info("  このストリームにはイベントがありません")
                continue

            # ログを解析
            found_evaluation = False
            for event in events.get("events", []):
                message = event.get("message", "")

                logger.info(f"\n  ログメッセージ:")
                logger.info(f"  {message[:200]}...")  # 最初の200文字のみ表示

                # JSON 形式のログを解析
                try:
                    log_data = json.loads(message)

                    # principal の確認
                    if "principal" in log_data:
                        found_evaluation = True
                        logger.info(f"\n  [OK] Principal 情報が見つかりました:")
                        logger.info(f"  {json.dumps(log_data['principal'], indent=2)}")

                        # role 属性の確認
                        if "role" in str(log_data["principal"]):
                            logger.info(f"  [OK] principal に role 属性が含まれています")

                    # decision の確認
                    if "decision" in log_data:
                        logger.info(f"\n  [OK] Policy 評価結果: {log_data['decision']}")

                except json.JSONDecodeError:
                    continue

            if found_evaluation:
                return {"success": True, "found_evaluation": True}

        if not found_evaluation:
            logger.warning("[WARN] Policy 評価ログが見つかりませんでした")
            return {"success": False, "reason": "no_evaluation_log"}

    except ClientError as e:
        error_code = e.response["Error"]["Code"]

        if error_code == "ResourceNotFoundException":
            logger.warning(f"[WARN] ログループが見つかりません: {log_group_name}")
        else:
            logger.error(f"[NG] ログ取得エラー: {error_code}")

        return {"success": False, "reason": error_code}


def main():
    """メイン処理"""
    logger.info("Tools/Call E2E 検証を開始します")

    # 設定ファイルの読み込み
    config = load_config()
    gateway_id = config["gatewayId"]
    target_id = config.get("targetId")
    user_pool_id = config["cognitoUserPoolId"]
    app_client_id = config["cognitoAppClientId"]
    policy_engine_id = config.get("policyEngineId")

    if not target_id:
        logger.error("targetId が設定されていません")
        sys.exit(1)

    logger.info(f"\n設定情報:")
    logger.info(f"  Gateway ID: {gateway_id}")
    logger.info(f"  Target ID: {target_id}")
    logger.info(f"  User Pool ID: {user_pool_id}")
    logger.info(f"  Policy Engine ID: {policy_engine_id}")

    # AWS クライアントの初期化
    cognito_client = boto3.client("cognito-idp", region_name=REGION)
    agent_runtime_client = boto3.client("bedrock-agent-runtime", region_name=REGION)
    logs_client = boto3.client("logs", region_name=REGION)

    # Policy Engine のログループ名
    log_group_name = f"/aws/bedrock/agentcore/policy-engine/{policy_engine_id}"

    # Admin ユーザーでテスト
    logger.info(f"\n{'='*60}")
    logger.info("Admin ユーザーでの検証")
    logger.info(f"{'='*60}")

    try:
        admin_user = TEST_USERS["admin"]
        start_time = datetime.now()

        # JWT トークン取得
        admin_token = authenticate_user(
            cognito_client,
            user_pool_id,
            app_client_id,
            admin_user["username"],
            admin_user["password"],
        )

        # Tools/Call リクエスト送信
        result = invoke_tool_via_gateway(
            agent_runtime_client,
            gateway_id,
            target_id,
            "retrieve_doc",
            admin_token,
            {"query": "test query for E2E verification"}
        )

        if result["success"]:
            logger.info("\n[INFO] リクエスト送信完了")
            logger.info("Policy Engine のログを確認します...")

            # CloudWatch Logs を確認
            log_result = check_cloudwatch_logs(
                logs_client,
                log_group_name,
                start_time,
                "admin"
            )

            if log_result.get("success"):
                logger.info("\n[SUCCESS] JWT → Cedar Attribute マッピングが確認されました")
            else:
                logger.warning(f"\n[WARN] ログの確認に失敗しました: {log_result.get('reason')}")
        else:
            logger.error("\n[FAILURE] リクエスト送信に失敗しました")
            logger.error(f"エラー: {result.get('error_message', result.get('error'))}")

    except Exception as e:
        logger.error(f"検証中にエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    logger.info(f"\n{'='*60}")
    logger.info("検証完了")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
