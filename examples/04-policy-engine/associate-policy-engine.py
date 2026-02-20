#!/usr/bin/env python3
"""
Policy Engine を Gateway に関連付けるスクリプト

update_gateway API を使用して、既存の Gateway に Policy Engine を関連付ける。
"""

import boto3
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REGION = "us-east-1"
CONFIG_FILE = "gateway-config.json"


def load_config():
    """gateway-config.json を読み込む"""
    with open(CONFIG_FILE) as f:
        return json.load(f)


def associate_policy_engine(client, config):
    """Gateway に Policy Engine を関連付ける"""
    gateway_id = config["gatewayId"]
    policy_engine_arn = config["policyEngineArn"]

    logger.info("Gateway の現在の設定を取得中: %s", gateway_id)

    # Gateway の現在の設定を取得
    response = client.get_gateway(gatewayIdentifier=gateway_id)

    # ResponseMetadata など不要な項目を削除
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
            "mode": "LOG_ONLY"
        }
    }

    # 任意のフィールドを追加
    if response.get("protocolConfiguration"):
        update_params["protocolConfiguration"] = response["protocolConfiguration"]
    if response.get("interceptorConfigurations"):
        update_params["interceptorConfigurations"] = response["interceptorConfigurations"]

    logger.info("Policy Engine を Gateway に関連付け中: mode=LOG_ONLY")

    # Gateway を更新
    update_response = client.update_gateway(**update_params)

    logger.info("関連付け完了: status=%s", update_response.get("status"))

    # config ファイルを更新
    config["policyEngineMode"] = "LOG_ONLY"
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, default=str)

    logger.info("設定ファイルを更新しました: %s", CONFIG_FILE)

    return update_response


def main():
    config = load_config()

    if not config.get("policyEngineArn"):
        logger.error("policyEngineArn が設定されていません")
        sys.exit(1)

    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    try:
        associate_policy_engine(client, config)
        logger.info("[OK] Policy Engine の関連付けが完了しました")
    except Exception as e:
        logger.error("関連付けに失敗しました: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
