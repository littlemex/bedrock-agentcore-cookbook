#!/usr/bin/env python3
"""
Cedar Policy 更新スクリプト

既存の Policy Engine に新しい Cedar Policy を登録します。
古い hasTag/getTag 構文を has / ドット記法に更新したポリシーを適用します。

Usage:
  python update-cedar-policies.py
"""

import json
import logging
import os
import sys
from pathlib import Path

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
POLICIES_DIR = os.path.join(SCRIPT_DIR, "policies")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def load_config() -> dict:
    """gateway-config.json を読み込む。"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"gateway-config.json が見つかりません: {CONFIG_FILE}")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    return config


def save_config(config: dict):
    """gateway-config.json に設定を保存する。"""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def delete_existing_policy(client, policy_engine_id: str, policy_id: str) -> bool:
    """既存のポリシーを削除する。"""
    try:
        logger.info(f"既存のポリシーを削除中: {policy_id}")
        client.delete_policy(
            policyEngineId=policy_engine_id,
            policyId=policy_id
        )
        logger.info(f"[OK] ポリシーを削除しました: {policy_id}")
        return True
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ResourceNotFoundException":
            logger.warning(f"[WARN] ポリシーが見つかりません: {policy_id}")
            return True
        else:
            logger.error(f"[NG] ポリシー削除エラー: {error_code}")
            return False


def register_policy(client, policy_engine_id: str, policy_name: str, policy_content: str) -> dict:
    """Cedar Policy を Policy Engine に登録する。"""
    logger.info(f"ポリシーを登録中: {policy_name}")

    try:
        response = client.create_policy(
            policyEngineId=policy_engine_id,
            name=policy_name,
            definition={
                "cedar": {
                    "statement": policy_content
                }
            },
            description=f"Updated policy with correct Cedar syntax: {policy_name}",
            validationMode="IGNORE_ALL_FINDINGS",
        )

        policy_id = response.get("policyId")
        logger.info(f"[OK] ポリシーを登録しました: {policy_name} (ID: {policy_id})")

        return {
            "policyId": policy_id,
            "policyName": policy_name,
            "status": "REGISTERED"
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"[NG] ポリシー登録エラー: {error_code} - {error_msg}")
        raise


def main():
    """メイン処理"""
    logger.info("=" * 60)
    logger.info("Cedar Policy 更新")
    logger.info("=" * 60)

    # 設定ファイルの読み込み
    config = load_config()
    policy_engine_id = config.get("policyEngineId")

    if not policy_engine_id:
        logger.error("policyEngineId が設定されていません")
        sys.exit(1)

    logger.info(f"\n設定情報:")
    logger.info(f"  Policy Engine ID: {policy_engine_id}")
    logger.info(f"  Mode: {config.get('policyEngineMode', 'UNKNOWN')}")

    # AWS クライアントの初期化
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # 既存のポリシーを削除
    logger.info(f"\n{'='*60}")
    logger.info("[STEP 1] 既存のポリシーを削除")
    logger.info(f"{'='*60}")

    existing_policies = config.get("registeredPolicies", [])
    for policy_info in existing_policies:
        policy_id = policy_info.get("policyId")
        if policy_id:
            delete_existing_policy(client, policy_engine_id, policy_id)

    # 新しいポリシーを登録
    logger.info(f"\n{'='*60}")
    logger.info("[STEP 2] 新しいポリシーを登録")
    logger.info(f"{'='*60}")

    # policies/ ディレクトリから .cedar ファイルを読み込む
    policies_path = Path(POLICIES_DIR)
    cedar_files = sorted(policies_path.glob("*.cedar"))

    if not cedar_files:
        logger.error(f"Cedar ポリシーファイルが見つかりません: {POLICIES_DIR}")
        sys.exit(1)

    registered_policies = []

    for cedar_file in cedar_files:
        policy_name = cedar_file.stem.replace("-", "_")  # ファイル名（拡張子なし）、ハイフンをアンダースコアに置換

        logger.info(f"\n読み込み中: {cedar_file.name}")

        with open(cedar_file, "r") as f:
            policy_content = f.read()

        # ポリシーを登録
        try:
            policy_info = register_policy(
                client,
                policy_engine_id,
                policy_name,
                policy_content
            )
            registered_policies.append(policy_info)

        except Exception as e:
            logger.error(f"ポリシー登録に失敗しました: {cedar_file.name}")
            logger.error(f"エラー: {e}")
            sys.exit(1)

    # 設定ファイルを更新
    config["registeredPolicies"] = registered_policies
    config["updated_at"] = json.dumps({"timestamp": "updated"})
    save_config(config)

    logger.info(f"\n{'='*60}")
    logger.info("完了")
    logger.info(f"{'='*60}")
    logger.info(f"\n登録されたポリシー:")
    for policy in registered_policies:
        logger.info(f"  - {policy['policyName']} (ID: {policy['policyId']})")

    logger.info(f"\n[SUCCESS] 全てのポリシーを更新しました")


if __name__ == "__main__":
    main()
