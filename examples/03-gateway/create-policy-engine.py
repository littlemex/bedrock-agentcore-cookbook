#!/usr/bin/env python3
"""
Policy Engine 作成スクリプト

Gateway に関連付ける Policy Engine を作成します。
Policy Engine はログのみ記録する LOG_ONLY モードと、
実際にアクセス制御を行う ENFORCE モードをサポートします。

Usage:
  # LOG_ONLY モードで作成
  python3 create-policy-engine.py --mode LOG_ONLY

  # ENFORCE モードで作成
  python3 create-policy-engine.py --mode ENFORCE

  # Policy Engine ID のみ取得
  python3 create-policy-engine.py --get-id
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
POLICY_ENGINE_NAME = "e2e-phase3-policy-engine"


def find_existing_policy_engine(client) -> dict:
    """既存の Policy Engine を検索する"""
    try:
        response = client.list_policy_engines(maxResults=100)
        engines = response.get("policyEngines", [])

        for engine in engines:
            if engine.get("name") == POLICY_ENGINE_NAME:
                logger.info("既存の Policy Engine を発見しました")
                logger.info("  Name: %s", engine.get("name"))
                logger.info("  ID: %s", engine.get("policyEngineId"))
                logger.info("  Mode: %s", engine.get("mode"))
                logger.info("  Status: %s", engine.get("status"))
                return engine

        return None
    except ClientError as e:
        logger.warning("Policy Engine の検索に失敗しました: %s", e)
        return None


def create_policy_engine(client, mode: str, gateway_id: str) -> dict:
    """
    Policy Engine を作成する

    Args:
        mode: "LOG_ONLY" または "ENFORCE"
        gateway_id: Gateway ID
    """
    logger.info("=" * 80)
    logger.info("Policy Engine を作成します")
    logger.info("=" * 80)
    logger.info("  Name: %s", POLICY_ENGINE_NAME)
    logger.info("  Mode: %s", mode)
    logger.info("  Gateway ID: %s", gateway_id)

    try:
        response = client.create_policy_engine(
            name=POLICY_ENGINE_NAME,
            mode=mode,
            policyStoreDescription="E2E Phase 3 検証用の Policy Engine",
        )

        policy_engine_id = response.get("policyEngineId")
        policy_engine_arn = response.get("policyEngineArn")

        logger.info("\n[SUCCESS] Policy Engine を作成しました")
        logger.info("  Policy Engine ID: %s", policy_engine_id)
        logger.info("  Policy Engine ARN: %s", policy_engine_arn)

        # ステータスが ACTIVE になるまで待機
        logger.info("\nPolicy Engine のステータスを確認中...")
        max_wait = 60
        waited = 0
        while waited < max_wait:
            check_response = client.get_policy_engine(
                policyEngineId=policy_engine_id
            )
            status = check_response.get("status")
            logger.info("  Status: %s (waited %ds)", status, waited)

            if status == "ACTIVE":
                logger.info("[OK] Policy Engine が ACTIVE になりました")
                break

            if status == "FAILED":
                logger.error("[ERROR] Policy Engine の作成に失敗しました")
                return None

            time.sleep(5)
            waited += 5

        if waited >= max_wait:
            logger.warning("[WARNING] タイムアウト: Policy Engine がまだ ACTIVE になっていません")

        # Gateway に Policy Engine を関連付け
        logger.info("\nGateway に Policy Engine を関連付けています...")
        try:
            client.associate_policy_engine(
                gatewayIdentifier=gateway_id,
                policyEngineId=policy_engine_id
            )
            logger.info("[OK] Gateway への関連付けが完了しました")
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "ConflictException":
                logger.info("[INFO] Policy Engine は既に Gateway に関連付けられています")
            else:
                logger.error("[ERROR] Gateway への関連付けに失敗: %s", e)

        return {
            "policyEngineId": policy_engine_id,
            "policyEngineArn": policy_engine_arn,
            "mode": mode,
            "status": status,
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "ConflictException":
            logger.info("[INFO] 同名の Policy Engine が既に存在します")
            logger.info("既存の Policy Engine を使用してください")
            return None
        else:
            logger.error("[ERROR] Policy Engine の作成に失敗: %s - %s", error_code, error_msg)
            return None


def update_policy_engine_mode(client, policy_engine_id: str, new_mode: str):
    """Policy Engine のモードを変更する"""
    logger.info("=" * 80)
    logger.info("Policy Engine のモードを変更します")
    logger.info("=" * 80)
    logger.info("  Policy Engine ID: %s", policy_engine_id)
    logger.info("  New Mode: %s", new_mode)

    try:
        response = client.update_policy_engine(
            policyEngineId=policy_engine_id,
            mode=new_mode
        )

        logger.info("[SUCCESS] Policy Engine のモードを変更しました")
        logger.info("  Updated at: %s", response.get("lastModifiedAt"))

        # 変更を確認
        time.sleep(2)
        check_response = client.get_policy_engine(
            policyEngineId=policy_engine_id
        )
        current_mode = check_response.get("mode")
        logger.info("  Current Mode: %s", current_mode)

        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error("[ERROR] モード変更に失敗: %s - %s", error_code, error_msg)
        return False


def get_policy_engine_info(client, policy_engine_id: str) -> dict:
    """Policy Engine の詳細情報を取得する"""
    try:
        response = client.get_policy_engine(
            policyEngineId=policy_engine_id
        )
        return {
            "policyEngineId": response.get("policyEngineId"),
            "name": response.get("name"),
            "mode": response.get("mode"),
            "status": response.get("status"),
            "description": response.get("description"),
            "createdAt": response.get("createdAt"),
            "lastModifiedAt": response.get("lastModifiedAt"),
        }
    except ClientError as e:
        logger.error("Policy Engine 情報の取得に失敗: %s", e)
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Policy Engine を作成・管理する"
    )
    parser.add_argument(
        "--mode",
        choices=["LOG_ONLY", "ENFORCE"],
        default="LOG_ONLY",
        help="Policy Engine のモード"
    )
    parser.add_argument(
        "--gateway-id",
        help="Gateway ID（環境変数 GATEWAY_ID から取得可能）"
    )
    parser.add_argument(
        "--get-id",
        action="store_true",
        help="既存の Policy Engine ID のみを出力して終了"
    )
    parser.add_argument(
        "--update-mode",
        choices=["LOG_ONLY", "ENFORCE"],
        help="既存の Policy Engine のモードを変更"
    )

    args = parser.parse_args()

    # Gateway ID の取得
    gateway_id = args.gateway_id or os.environ.get("GATEWAY_ID")
    if not gateway_id and not args.get_id and not args.update_mode:
        logger.error("Gateway ID が指定されていません")
        logger.info("Hint: export GATEWAY_ID=xxx または --gateway-id オプションを使用")
        sys.exit(1)

    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # 既存の Policy Engine を検索
    existing = find_existing_policy_engine(client)

    # --get-id オプション
    if args.get_id:
        if existing:
            print(existing.get("policyEngineId"))
            sys.exit(0)
        else:
            logger.error("Policy Engine が見つかりません")
            sys.exit(1)

    # --update-mode オプション
    if args.update_mode:
        if not existing:
            logger.error("Policy Engine が見つかりません")
            sys.exit(1)

        policy_engine_id = existing.get("policyEngineId")
        success = update_policy_engine_mode(client, policy_engine_id, args.update_mode)
        sys.exit(0 if success else 1)

    # Policy Engine 作成
    if existing:
        logger.info("=" * 80)
        logger.info("既存の Policy Engine が見つかりました")
        logger.info("=" * 80)

        # 詳細情報を表示
        info = get_policy_engine_info(client, existing.get("policyEngineId"))
        if info:
            logger.info("  Policy Engine ID: %s", info.get("policyEngineId"))
            logger.info("  Name: %s", info.get("name"))
            logger.info("  Mode: %s", info.get("mode"))
            logger.info("  Status: %s", info.get("status"))
            logger.info("  Created At: %s", info.get("createdAt"))
            logger.info("  Last Modified: %s", info.get("lastModifiedAt"))

        logger.info("\n既存の Policy Engine を使用する場合:")
        logger.info("  export POLICY_ENGINE_ID=%s", existing.get("policyEngineId"))
        logger.info("\nモードを変更する場合:")
        logger.info("  python3 create-policy-engine.py --update-mode ENFORCE")
        sys.exit(0)

    result = create_policy_engine(client, args.mode, gateway_id)

    if result:
        logger.info("\n" + "=" * 80)
        logger.info("環境変数を設定してください:")
        logger.info("=" * 80)
        logger.info("  export POLICY_ENGINE_ID=%s", result["policyEngineId"])
        logger.info("\n次のステップ:")
        logger.info("  1. Cedar ポリシーを登録: python3 put-cedar-policies.py")
        logger.info("  2. 検証実行: python3 test-phase3.py")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
