#!/usr/bin/env python3
"""
Policy Engine Mode 切り替えスクリプト

Gateway に関連付けられた Policy Engine のモードを切り替えます：
- LOG_ONLY: ポリシー評価をログに記録するが、アクセスは許可する（デバッグ用）
- ENFORCE: ポリシー評価に基づいて実際にアクセスを制御する

Usage:
    # LOG_ONLY モードに設定
    python update-policy-engine-mode.py --mode LOG_ONLY

    # ENFORCE モードに設定
    python update-policy-engine-mode.py --mode ENFORCE

    # 現在のモードを確認
    python update-policy-engine-mode.py --get-mode
"""

import argparse
import json
import logging
import os
import sys

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


def load_config() -> dict:
    """gateway-config.json を読み込む"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"gateway-config.json が見つかりません: {CONFIG_FILE}")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    required_fields = ["gatewayId", "policyEngineArn"]
    missing = [f for f in required_fields if f not in config]
    if missing:
        logger.error(f"gateway-config.json に必須フィールドがありません: {missing}")
        sys.exit(1)

    return config


def save_config(config: dict):
    """gateway-config.json を保存する"""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, default=str)
    logger.info(f"設定ファイルを更新しました: {CONFIG_FILE}")


def get_current_mode(client, gateway_id: str) -> str:
    """
    Gateway に関連付けられた Policy Engine の現在のモードを取得する

    Returns:
        現在のモード（LOG_ONLY または ENFORCE）
    """
    logger.info("=" * 80)
    logger.info("Gateway の現在の Policy Engine モードを取得します")
    logger.info("=" * 80)
    logger.info(f"  Gateway ID: {gateway_id}")

    try:
        response = client.get_gateway(gatewayIdentifier=gateway_id)

        policy_engine_config = response.get("policyEngineConfiguration")
        if not policy_engine_config:
            logger.error("[ERROR] Policy Engine が Gateway に関連付けられていません")
            return None

        mode = policy_engine_config.get("mode")
        arn = policy_engine_config.get("arn")

        logger.info("\n[OK] 現在のモード:")
        logger.info(f"  Mode: {mode}")
        logger.info(f"  Policy Engine ARN: {arn}")

        return mode

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"[ERROR] Gateway 情報の取得に失敗: {error_code} - {error_msg}")
        return None


def update_policy_engine_mode(client, config: dict, new_mode: str) -> bool:
    """
    Policy Engine のモードを変更する

    Args:
        new_mode: 新しいモード（LOG_ONLY または ENFORCE）

    Returns:
        成功時 True
    """
    gateway_id = config["gatewayId"]
    policy_engine_arn = config["policyEngineArn"]

    logger.info("=" * 80)
    logger.info("Policy Engine のモードを変更します")
    logger.info("=" * 80)
    logger.info(f"  Gateway ID: {gateway_id}")
    logger.info(f"  Policy Engine ARN: {policy_engine_arn}")
    logger.info(f"  New Mode: {new_mode}")

    # 現在の Gateway 設定を取得
    logger.info("\nGateway の現在の設定を取得中...")
    try:
        response = client.get_gateway(gatewayIdentifier=gateway_id)
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"[ERROR] Gateway 情報の取得に失敗: {error_code} - {error_msg}")
        return False

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

    logger.info(f"\nPolicy Engine モードを {new_mode} に変更中...")

    # Gateway を更新
    try:
        update_response = client.update_gateway(**update_params)
        logger.info("\n[SUCCESS] モードを変更しました")
        logger.info(f"  Status: {update_response.get('status')}")

        # config ファイルを更新
        config["policyEngineMode"] = new_mode
        save_config(config)

        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"[ERROR] モード変更に失敗: {error_code} - {error_msg}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Policy Engine Mode 切り替えスクリプト"
    )

    # サブコマンド
    parser.add_argument(
        "--mode",
        choices=["LOG_ONLY", "ENFORCE"],
        help="新しいモードを指定"
    )
    parser.add_argument(
        "--get-mode",
        action="store_true",
        help="現在のモードを確認"
    )

    args = parser.parse_args()

    # 環境変数からリージョンを取得
    logger.info(f"AWS Region: {REGION}")

    # 設定ファイルを読み込む
    config = load_config()

    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # --get-mode: 現在のモードを確認
    if args.get_mode:
        mode = get_current_mode(client, config["gatewayId"])
        if mode:
            print(mode)
            sys.exit(0)
        else:
            sys.exit(1)

    # --mode: モードを変更
    if args.mode:
        success = update_policy_engine_mode(client, config, args.mode)
        if success:
            logger.info("\n" + "=" * 80)
            logger.info("モード変更が完了しました")
            logger.info("=" * 80)
            logger.info(f"  New Mode: {args.mode}")

            if args.mode == "ENFORCE":
                logger.info("\n[IMPORTANT] ENFORCE モードでは、Cedar Policy に基づいて実際にアクセス制御が行われます")
                logger.info("  - role=admin: 全ツールへのアクセスが許可されます")
                logger.info("  - role=user: 制限されたツールのみアクセス可能です")
                logger.info("  - ポリシーにマッチしないリクエストは拒否されます")
            else:
                logger.info("\n[INFO] LOG_ONLY モードでは、ポリシー評価がログに記録されますが、アクセスは許可されます")

            sys.exit(0)
        else:
            sys.exit(1)

    # デフォルト: ヘルプを表示
    parser.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
