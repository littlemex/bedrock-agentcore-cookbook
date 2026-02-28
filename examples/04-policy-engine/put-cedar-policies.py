#!/usr/bin/env python3
"""
E2E Phase 3: Cedar ポリシー投入スクリプト

Policy Engine に Cedar ポリシーを登録する。

前提条件:
  - boto3 >= 1.42.0
  - gateway-config.json に policyEngineId が設定済み

Usage:
  python3 put-cedar-policies.py [--policy-dir POLICY_DIR]

出力:
  gateway-config.json に登録したポリシー情報を追記
"""

import argparse
import json
import logging
import os
import sys
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
DEFAULT_POLICY_DIR = os.path.join(SCRIPT_DIR, "policies")

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def load_config() -> dict:
    """gateway-config.json を読み込む。"""
    if not os.path.exists(CONFIG_FILE):
        logger.error("gateway-config.json が見つかりません。")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config: dict) -> None:
    """設定ファイルを保存する。"""
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, default=str)
    logger.info("設定を保存しました: %s", CONFIG_FILE)


def put_cedar_policy(
    bedrock_client,
    policy_engine_id: str,
    policy_name: str,
    policy_content: str,
) -> dict:
    """
    Cedar ポリシーを Policy Engine に登録する。

    Args:
        bedrock_client: boto3 bedrock-agent クライアント
        policy_engine_id: Policy Engine ID
        policy_name: ポリシー名
        policy_content: Cedar ポリシーの内容

    Returns:
        登録結果の辞書
    """
    logger.info("Cedar ポリシーを登録中: name=%s", policy_name)
    logger.info("  Policy Engine ID: %s", policy_engine_id)
    logger.info("  ポリシー内容:")
    for line in policy_content.strip().split("\n"):
        logger.info("    %s", line)

    try:
        response = bedrock_client.create_policy(
            policyEngineId=policy_engine_id,
            name=policy_name,
            definition={
                "cedar": {
                    "statement": policy_content,
                }
            },
            description=f"E2E Phase 3 Policy: {policy_name}",
            validationMode="IGNORE_ALL_FINDINGS",
        )

        policy_id = response.get("policyId", "")
        logger.info("[OK] ポリシー '%s' を登録しました (id=%s)", policy_name, policy_id)

        return {
            "policyId": policy_id,
            "policyName": policy_name,
            "status": "REGISTERED",
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ConflictException":
            logger.info("ポリシー '%s' は既に登録済みです。更新を試みます。", policy_name)
            # 既存ポリシーの更新を試行
            try:
                response = bedrock_client.update_policy(
                    policyEngineId=policy_engine_id,
                    policyName=policy_name,
                    policyDefinition={
                        "cedar": {
                            "content": policy_content,
                        }
                    },
                )
                logger.info("[OK] ポリシー '%s' を更新しました。", policy_name)
                return {
                    "policyId": response.get("policyId", ""),
                    "policyName": policy_name,
                    "status": "UPDATED",
                }
            except ClientError as update_err:
                logger.warning("ポリシーの更新に失敗: %s", update_err)
                return {
                    "policyName": policy_name,
                    "status": "ALREADY_EXISTS",
                }
        elif error_code == "ValidationException":
            logger.error("Cedar ポリシーのバリデーションエラー: %s", e)
            logger.error("ポリシー内容を確認してください。")
            return {
                "policyName": policy_name,
                "status": "VALIDATION_ERROR",
                "error": str(e),
            }
        else:
            raise


def load_policy_files(policy_dir: str) -> list[dict]:
    """ポリシーディレクトリから .cedar ファイルを読み込む。"""
    policies = []

    if not os.path.isdir(policy_dir):
        logger.error("ポリシーディレクトリが見つかりません: %s", policy_dir)
        sys.exit(1)

    # 環境変数からアカウント ID を取得
    account_id = os.environ.get("AWS_ACCOUNT_ID") or os.environ.get("ACCOUNT_ID")
    if not account_id:
        # boto3 から現在のアカウント ID を取得
        try:
            sts_client = boto3.client("sts")
            account_id = sts_client.get_caller_identity()["Account"]
            logger.info("現在のアカウント ID: %s", account_id)
        except Exception as e:
            logger.warning("アカウント ID の自動取得に失敗: %s", e)
            account_id = None

    for filename in sorted(os.listdir(policy_dir)):
        if not filename.endswith(".cedar"):
            continue

        filepath = os.path.join(policy_dir, filename)
        policy_name = filename.replace(".cedar", "").replace("-", "_")

        with open(filepath) as f:
            content = f.read()

        # 環境変数の置換
        if account_id and "${ACCOUNT_ID}" in content:
            logger.info("ポリシー '%s' で ${ACCOUNT_ID} を %s に置換", filename, account_id)
            content = content.replace("${ACCOUNT_ID}", account_id)

        policies.append({
            "name": policy_name,
            "content": content,
            "filepath": filepath,
        })
        logger.info("ポリシーファイルを読み込み: %s", filename)

    if not policies:
        logger.warning("ポリシーファイルが見つかりません: %s", policy_dir)

    return policies


def list_registered_policies(bedrock_client, policy_engine_id: str) -> list:
    """登録済みの Cedar ポリシー一覧を取得する。"""
    try:
        response = bedrock_client.list_policies(policyEngineId=policy_engine_id)
        policies = response.get("policies", [])
        logger.info("登録済みポリシー数: %d", len(policies))
        for p in policies:
            logger.info(
                "  - %s (id=%s)",
                p.get("policyName", ""),
                p.get("policyId", ""),
            )
        return policies
    except ClientError as e:
        logger.warning("ポリシー一覧の取得に失敗: %s", e)
        return []


def main():
    parser = argparse.ArgumentParser(description="E2E Phase 3: Cedar ポリシー投入")
    parser.add_argument(
        "--policy-dir",
        default=DEFAULT_POLICY_DIR,
        help="ポリシーファイルのディレクトリ (default: policies/)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="登録済みポリシーの一覧表示のみ",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("E2E Phase 3: Cedar ポリシー投入")
    logger.info("=" * 60)

    config = load_config()
    policy_engine_id = config.get("policyEngineId")

    if not policy_engine_id:
        logger.error("policyEngineId が設定されていません。create-policy-engine.py を先に実行してください。")
        sys.exit(1)

    bedrock_client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # 一覧表示のみ
    if args.list_only:
        list_registered_policies(bedrock_client, policy_engine_id)
        return

    # ポリシーファイルの読み込み
    logger.info("")
    logger.info("[STEP 1] ポリシーファイルの読み込み")
    logger.info("-" * 60)

    policies = load_policy_files(args.policy_dir)
    if not policies:
        logger.error("投入するポリシーがありません。")
        sys.exit(1)

    logger.info("読み込んだポリシー数: %d", len(policies))

    # ポリシーの登録
    logger.info("")
    logger.info("[STEP 2] ポリシーの登録")
    logger.info("-" * 60)

    results = []
    for policy in policies:
        result = put_cedar_policy(
            bedrock_client,
            policy_engine_id,
            policy["name"],
            policy["content"],
        )
        results.append(result)
        logger.info("")

    # 結果の保存
    config["registeredPolicies"] = results
    save_config(config)

    # 登録済みポリシーの確認
    logger.info("")
    logger.info("[STEP 3] 登録済みポリシーの確認")
    logger.info("-" * 60)
    list_registered_policies(bedrock_client, policy_engine_id)

    # サマリー
    logger.info("")
    logger.info("=" * 60)
    logger.info("[OK] Cedar ポリシー投入完了")
    logger.info("=" * 60)

    success = sum(1 for r in results if r["status"] in ("REGISTERED", "UPDATED", "ALREADY_EXISTS"))
    failed = sum(1 for r in results if r["status"] == "VALIDATION_ERROR")

    logger.info("  成功: %d / 失敗: %d / 全体: %d", success, failed, len(results))
    for r in results:
        status_marker = "[OK]" if r["status"] != "VALIDATION_ERROR" else "[FAIL]"
        logger.info("  %s %s (%s)", status_marker, r["policyName"], r["status"])

    logger.info("")
    logger.info("次のステップ: python3 test-phase3.py")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
