#!/usr/bin/env python3
"""
E2E Phase 3: Policy Engine 作成スクリプト

AgentCore Policy Engine を作成し、Gateway に関連付ける。
初期モードは LOG_ONLY で作成し、検証後に ENFORCE に切り替える。

前提条件:
  - boto3 >= 1.42.0
  - gateway-config.json が存在する（deploy-gateway.py で生成）

Usage:
  python3 create-policy-engine.py [--mode LOG_ONLY|ENFORCE]

出力:
  gateway-config.json に Policy Engine 情報を追記
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

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
POLICY_ENGINE_NAME = "e2e_phase3_policy_engine"


def load_config() -> dict:
    """gateway-config.json を読み込む。"""
    if not os.path.exists(CONFIG_FILE):
        logger.error("gateway-config.json が見つかりません。deploy-gateway.py を先に実行してください。")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config: dict) -> None:
    """設定ファイルを保存する。"""
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, default=str)
    logger.info("設定を保存しました: %s", CONFIG_FILE)


def create_policy_engine(
    bedrock_client,
    gateway_id: str,
    engine_name: str,
    mode: str = "LOG_ONLY",
) -> dict:
    """
    Policy Engine を作成する。

    Args:
        bedrock_client: boto3 bedrock-agent クライアント
        gateway_id: AgentCore Gateway ID
        engine_name: Policy Engine 名
        mode: "LOG_ONLY" または "ENFORCE"

    Returns:
        Policy Engine の情報を含む辞書
    """
    logger.info("Policy Engine を作成中: name=%s (mode は Gateway 関連付け時に設定)", engine_name)

    try:
        response = bedrock_client.create_policy_engine(
            name=engine_name,
            description="E2E Phase 3 Policy Engine for Cedar FGAC verification",
        )

        policy_engine_id = response.get("policyEngineId", "")
        policy_engine_arn = response.get("policyEngineArn", "")

        logger.info("Policy Engine を作成しました: id=%s", policy_engine_id)

        # ステータス確認
        for i in range(20):
            time.sleep(5)
            status_response = bedrock_client.get_policy_engine(
                policyEngineId=policy_engine_id
            )
            status = status_response.get("status", "")
            logger.info("  Policy Engine ステータス: %s (%d/20)", status, i + 1)
            if status in ("ACTIVE", "READY", "AVAILABLE"):
                break
            if status in ("FAILED", "CREATE_FAILED"):
                raise RuntimeError(
                    f"Policy Engine 作成が失敗しました: {status}"
                )

        return {
            "policyEngineId": policy_engine_id,
            "policyEngineArn": policy_engine_arn,
            "mode": mode,
            "status": status,
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ConflictException":
            logger.info("同名の Policy Engine が既に存在します。検索します。")
            return find_existing_policy_engine(bedrock_client, engine_name)
        raise


def find_existing_policy_engine(bedrock_client, engine_name: str) -> dict:
    """既存の Policy Engine を名前で検索する。"""
    try:
        response = bedrock_client.list_policy_engines()
        for pe in response.get("policyEngines", []):
            if pe.get("name") == engine_name:
                pe_id = pe["policyEngineId"]
                logger.info("既存の Policy Engine を発見: id=%s", pe_id)
                detail = bedrock_client.get_policy_engine(policyEngineId=pe_id)
                return {
                    "policyEngineId": pe_id,
                    "policyEngineArn": detail.get("policyEngineArn", ""),
                    "mode": detail.get("mode", ""),
                    "status": detail.get("status", ""),
                }
    except ClientError:
        pass

    raise RuntimeError(f"Policy Engine '{engine_name}' が見つかりません。")


def attach_policy_engine_to_gateway(
    bedrock_client,
    gateway_id: str,
    policy_engine_id: str,
) -> None:
    """
    Policy Engine を Gateway に関連付ける。

    注意: API 名は boto3 のバージョンによって異なる可能性がある。
    候補: attach_policy_engine, update_gateway, associate_policy_engine
    """
    logger.info(
        "Policy Engine を Gateway に関連付け中: gateway=%s, engine=%s",
        gateway_id, policy_engine_id,
    )

    try:
        # 方法 1: attach_policy_engine API
        bedrock_client.attach_policy_engine(
            gatewayIdentifier=gateway_id,
            policyEngineId=policy_engine_id,
        )
        logger.info("[OK] Policy Engine を Gateway に関連付けました。")
        return
    except (ClientError, AttributeError) as e:
        logger.warning("attach_policy_engine API が利用不可: %s", e)

    try:
        # 方法 2: update_gateway API で Policy Engine を設定
        bedrock_client.update_gateway(
            gatewayIdentifier=gateway_id,
            policyEngineConfiguration={
                "policyEngineId": policy_engine_id,
            },
        )
        logger.info("[OK] update_gateway で Policy Engine を設定しました。")
        return
    except (ClientError, AttributeError) as e:
        logger.warning("update_gateway での設定が利用不可: %s", e)

    logger.warning("[WARNING] 自動関連付けに失敗しました。")
    logger.warning("AWS Console から手動で Gateway に Policy Engine を関連付けてください。")
    logger.warning("  Gateway ID: %s", gateway_id)
    logger.warning("  Policy Engine ID: %s", policy_engine_id)


def update_policy_engine_mode(
    bedrock_client,
    policy_engine_id: str,
    mode: str,
) -> dict:
    """
    Policy Engine のモードを変更する。

    Args:
        mode: "LOG_ONLY" または "ENFORCE"
    """
    logger.info(
        "Policy Engine のモードを変更中: id=%s, mode=%s",
        policy_engine_id, mode,
    )

    try:
        response = bedrock_client.update_policy_engine(
            policyEngineId=policy_engine_id,
            mode=mode,
        )
        logger.info("[OK] Policy Engine モードを %s に変更しました。", mode)
        return response
    except ClientError as e:
        logger.error("モード変更に失敗: %s", e)
        raise


def main():
    parser = argparse.ArgumentParser(description="E2E Phase 3: Policy Engine 作成")
    parser.add_argument(
        "--mode",
        choices=["LOG_ONLY", "ENFORCE"],
        default="LOG_ONLY",
        help="初期モード (default: LOG_ONLY)",
    )
    parser.add_argument(
        "--switch-mode",
        choices=["LOG_ONLY", "ENFORCE"],
        help="既存の Policy Engine のモードを切り替え",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("E2E Phase 3: Policy Engine 作成")
    logger.info("=" * 60)

    config = load_config()
    gateway_id = config.get("gatewayId")

    if not gateway_id:
        logger.error("gatewayId が設定されていません。deploy-gateway.py を先に実行してください。")
        sys.exit(1)

    bedrock_client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # モード切替のみの場合
    if args.switch_mode:
        policy_engine_id = config.get("policyEngineId")
        if not policy_engine_id:
            logger.error("policyEngineId が設定されていません。")
            sys.exit(1)

        update_policy_engine_mode(bedrock_client, policy_engine_id, args.switch_mode)
        config["policyEngineMode"] = args.switch_mode
        save_config(config)
        return

    # Step 1: Policy Engine の作成
    logger.info("")
    logger.info("[STEP 1] Policy Engine の作成")
    logger.info("-" * 60)

    try:
        engine_info = create_policy_engine(
            bedrock_client, gateway_id, POLICY_ENGINE_NAME, args.mode
        )
        config["policyEngineId"] = engine_info["policyEngineId"]
        config["policyEngineArn"] = engine_info.get("policyEngineArn", "")
        config["policyEngineMode"] = engine_info["mode"]
        save_config(config)
    except Exception as e:
        logger.error("Policy Engine 作成に失敗しました: %s", e)
        logger.info("")
        logger.info("[代替手順]")
        logger.info("  1. AWS Console から Policy Engine を手動で作成")
        logger.info("  2. AWS 公式サンプルの Notebook を使用")
        logger.info("  3. gateway-config.json に policyEngineId を手動で設定")
        sys.exit(1)

    # Step 2: Gateway への関連付け
    logger.info("")
    logger.info("[STEP 2] Gateway への関連付け")
    logger.info("-" * 60)

    try:
        attach_policy_engine_to_gateway(
            bedrock_client, gateway_id, config["policyEngineId"]
        )
    except Exception as e:
        logger.warning("Gateway への関連付けに失敗しました: %s", e)
        logger.warning("手動での関連付けが必要な場合があります。")

    save_config(config)

    logger.info("")
    logger.info("=" * 60)
    logger.info("[OK] Policy Engine 作成完了")
    logger.info("=" * 60)
    logger.info("  Policy Engine ID: %s", config.get("policyEngineId"))
    logger.info("  モード: %s", config.get("policyEngineMode"))
    logger.info("  Gateway ID: %s", gateway_id)
    logger.info("")
    logger.info("次のステップ: python3 put-cedar-policies.py")


if __name__ == "__main__":
    main()
