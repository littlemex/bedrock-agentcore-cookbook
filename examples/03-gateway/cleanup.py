#!/usr/bin/env python3
"""
E2E Phase 3: クリーンアップスクリプト

Phase 3 で作成した AWS リソースを削除する。

Usage:
  python3 cleanup.py [--dry-run] [--skip-gateway] [--skip-lambda]

注意:
  このスクリプトは以下のリソースを削除します:
  - Policy Engine に登録された Cedar ポリシー
  - Policy Engine
  - Gateway ターゲット
  - AgentCore Gateway
  - Lambda 関数 (e2e-phase3-mcp-server)
  - IAM ロール (e2e-phase3-lambda-role)
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
    """gateway-config.json を読み込む。"""
    if not os.path.exists(CONFIG_FILE):
        logger.warning("gateway-config.json が見つかりません。")
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def cleanup_policies(bedrock_client, policy_engine_id: str, dry_run: bool) -> None:
    """Policy Engine から全ポリシーを削除する。"""
    logger.info("[STEP 1] Cedar ポリシーの削除")

    if not policy_engine_id:
        logger.info("  Policy Engine ID が未設定。スキップ。")
        return

    try:
        response = bedrock_client.list_policies(policyEngineId=policy_engine_id)
        policies = response.get("policies", [])
        logger.info("  登録済みポリシー数: %d", len(policies))

        for p in policies:
            policy_id = p.get("policyId", "")
            policy_name = p.get("policyName", "")
            if dry_run:
                logger.info("  [DRY-RUN] ポリシー '%s' (id=%s) を削除", policy_name, policy_id)
            else:
                try:
                    bedrock_client.delete_policy(
                        policyEngineId=policy_engine_id,
                        policyId=policy_id,
                    )
                    logger.info("  [OK] ポリシー '%s' を削除しました", policy_name)
                except ClientError as e:
                    logger.warning("  [WARNING] ポリシー '%s' の削除に失敗: %s", policy_name, e)

    except ClientError as e:
        logger.warning("  ポリシー一覧の取得に失敗: %s", e)


def cleanup_policy_engine(bedrock_client, policy_engine_id: str, dry_run: bool) -> None:
    """Policy Engine を削除する。"""
    logger.info("[STEP 2] Policy Engine の削除")

    if not policy_engine_id:
        logger.info("  Policy Engine ID が未設定。スキップ。")
        return

    if dry_run:
        logger.info("  [DRY-RUN] Policy Engine '%s' を削除", policy_engine_id)
        return

    try:
        bedrock_client.delete_policy_engine(policyEngineId=policy_engine_id)
        logger.info("  [OK] Policy Engine '%s' を削除しました", policy_engine_id)

        # 削除完了を待機
        for i in range(20):
            time.sleep(5)
            try:
                bedrock_client.get_policy_engine(policyEngineId=policy_engine_id)
                logger.info("  削除中... (%d/20)", i + 1)
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    logger.info("  [OK] Policy Engine の削除が完了しました")
                    return
                raise

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info("  Policy Engine は既に削除済みです")
        else:
            logger.warning("  Policy Engine の削除に失敗: %s", e)


def cleanup_gateway_target(
    bedrock_runtime_client, gateway_id: str, target_id: str, dry_run: bool,
) -> None:
    """Gateway ターゲットを削除する。"""
    logger.info("[STEP 3] Gateway ターゲットの削除")

    if not gateway_id or not target_id:
        logger.info("  Gateway/Target ID が未設定。スキップ。")
        return

    if dry_run:
        logger.info("  [DRY-RUN] ターゲット '%s' を削除 (Gateway: %s)", target_id, gateway_id)
        return

    try:
        bedrock_runtime_client.delete_gateway_target(
            gatewayId=gateway_id,
            targetId=target_id,
        )
        logger.info("  [OK] ターゲット '%s' を削除しました", target_id)
        time.sleep(5)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info("  ターゲットは既に削除済みです")
        else:
            logger.warning("  ターゲットの削除に失敗: %s", e)


def cleanup_gateway(bedrock_runtime_client, gateway_id: str, dry_run: bool) -> None:
    """AgentCore Gateway を削除する。"""
    logger.info("[STEP 4] AgentCore Gateway の削除")

    if not gateway_id:
        logger.info("  Gateway ID が未設定。スキップ。")
        return

    if dry_run:
        logger.info("  [DRY-RUN] Gateway '%s' を削除", gateway_id)
        return

    try:
        bedrock_runtime_client.delete_gateway(gatewayId=gateway_id)
        logger.info("  [OK] Gateway '%s' の削除を開始しました", gateway_id)

        for i in range(30):
            time.sleep(10)
            try:
                bedrock_runtime_client.get_gateway(gatewayId=gateway_id)
                logger.info("  削除中... (%d/30)", i + 1)
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    logger.info("  [OK] Gateway の削除が完了しました")
                    return
                raise

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info("  Gateway は既に削除済みです")
        else:
            logger.warning("  Gateway の削除に失敗: %s", e)


def cleanup_lambda(lambda_client, function_name: str, dry_run: bool) -> None:
    """Lambda 関数を削除する。"""
    logger.info("[STEP 5] Lambda 関数の削除")

    if dry_run:
        logger.info("  [DRY-RUN] Lambda '%s' を削除", function_name)
        return

    try:
        lambda_client.delete_function(FunctionName=function_name)
        logger.info("  [OK] Lambda '%s' を削除しました", function_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info("  Lambda '%s' は既に削除済みです", function_name)
        else:
            logger.warning("  Lambda の削除に失敗: %s", e)


def cleanup_iam_role(iam_client, role_name: str, dry_run: bool) -> None:
    """IAM ロールを削除する。"""
    logger.info("[STEP 6] IAM ロールの削除")

    if dry_run:
        logger.info("  [DRY-RUN] IAM ロール '%s' を削除", role_name)
        return

    try:
        # アタッチされたポリシーをデタッチ
        attached = iam_client.list_attached_role_policies(RoleName=role_name)
        for policy in attached.get("AttachedPolicies", []):
            iam_client.detach_role_policy(
                RoleName=role_name,
                PolicyArn=policy["PolicyArn"],
            )
            logger.info("  ポリシーをデタッチ: %s", policy["PolicyArn"])

        # インラインポリシーを削除
        inline = iam_client.list_role_policies(RoleName=role_name)
        for policy_name in inline.get("PolicyNames", []):
            iam_client.delete_role_policy(
                RoleName=role_name,
                PolicyName=policy_name,
            )
            logger.info("  インラインポリシーを削除: %s", policy_name)

        # ロールを削除
        iam_client.delete_role(RoleName=role_name)
        logger.info("  [OK] IAM ロール '%s' を削除しました", role_name)

    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            logger.info("  IAM ロール '%s' は既に削除済みです", role_name)
        else:
            logger.warning("  IAM ロールの削除に失敗: %s", e)


def main():
    parser = argparse.ArgumentParser(description="E2E Phase 3: クリーンアップ")
    parser.add_argument("--dry-run", action="store_true", help="削除を実行せず確認のみ")
    parser.add_argument("--skip-gateway", action="store_true", help="Gateway 削除をスキップ")
    parser.add_argument("--skip-lambda", action="store_true", help="Lambda 削除をスキップ")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("E2E Phase 3: クリーンアップ")
    if args.dry_run:
        logger.info("[DRY-RUN モード] 実際の削除は行いません")
    logger.info("=" * 60)

    config = load_config()

    # クライアントの初期化
    bedrock_agent_client = boto3.client("bedrock-agent", region_name=REGION)
    bedrock_runtime_client = boto3.client("bedrock-agent-runtime", region_name=REGION)
    lambda_client = boto3.client("lambda", region_name=REGION)
    iam_client = boto3.client("iam", region_name=REGION)

    # Step 1: Cedar ポリシーの削除
    logger.info("")
    cleanup_policies(
        bedrock_agent_client,
        config.get("policyEngineId", ""),
        args.dry_run,
    )

    # Step 2: Policy Engine の削除
    logger.info("")
    cleanup_policy_engine(
        bedrock_agent_client,
        config.get("policyEngineId", ""),
        args.dry_run,
    )

    if not args.skip_gateway:
        # Step 3: Gateway ターゲットの削除
        logger.info("")
        cleanup_gateway_target(
            bedrock_runtime_client,
            config.get("gatewayId", ""),
            config.get("targetId", ""),
            args.dry_run,
        )

        # Step 4: Gateway の削除
        logger.info("")
        cleanup_gateway(
            bedrock_runtime_client,
            config.get("gatewayId", ""),
            args.dry_run,
        )
    else:
        logger.info("")
        logger.info("[SKIP] Gateway 削除をスキップしました")

    if not args.skip_lambda:
        # Step 5: Lambda 関数の削除
        logger.info("")
        cleanup_lambda(
            lambda_client,
            config.get("lambdaFunctionName", "e2e-phase3-mcp-server"),
            args.dry_run,
        )

        # Step 6: IAM ロールの削除
        logger.info("")
        cleanup_iam_role(iam_client, "e2e-phase3-lambda-role", args.dry_run)
    else:
        logger.info("")
        logger.info("[SKIP] Lambda/IAM 削除をスキップしました")

    # 設定ファイルの削除
    if not args.dry_run and os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)
        logger.info("")
        logger.info("[OK] gateway-config.json を削除しました")

    logger.info("")
    logger.info("=" * 60)
    if args.dry_run:
        logger.info("[DRY-RUN] クリーンアップ確認完了（実際の削除は行っていません）")
    else:
        logger.info("[OK] クリーンアップ完了")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
