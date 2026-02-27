#!/usr/bin/env python3
"""
Cedar Policy Engine レイテンシーベンチマーク

Cedar Policy Engine の IsAuthorized API のレイテンシーを測定する。
LOG_ONLY モードと ENFORCE モードの比較、各種リクエストパターンの
平均・中央値・P95・P99 を計測する。

前提条件:
- Gateway がデプロイ済み
- Policy Engine が Gateway に関連付け済み
- Cedar ポリシーが登録済み
- Cognito User Pool とテストユーザーが作成済み
- phase14-config.json が存在する

Usage:
  python3 benchmark-cedar-latency.py
  python3 benchmark-cedar-latency.py --iterations 500
  python3 benchmark-cedar-latency.py --dry-run

環境変数:
  AWS_DEFAULT_REGION: AWS リージョン（デフォルト: us-east-1）
"""

import argparse
import json
import logging
import os
import statistics
import sys
import time
from typing import Any

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
CONFIG_FILE = os.path.join(SCRIPT_DIR, "phase14-config.json")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

# ウォームアップ回数（統計から除外）
WARMUP_COUNT = 10


def load_config() -> dict:
    """phase14-config.json を読み込む"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"設定ファイルが見つかりません: {CONFIG_FILE}")
        logger.info("Hint: phase14-config.json.example をコピーして設定してください")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    required_fields = ["region", "gatewayId", "policyEngineId"]
    missing = [f for f in required_fields if f not in config]
    if missing:
        logger.error(f"設定ファイルに必須フィールドがありません: {missing}")
        sys.exit(1)

    return config


def get_jwt_token(cognito_client, config: dict, username: str, password: str) -> str:
    """Cognito User Pool からユーザー認証して JWT トークンを取得する"""
    try:
        response = cognito_client.initiate_auth(
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": username,
                "PASSWORD": password,
            },
            ClientId=config["cognitoAppClientId"],
        )
        return response["AuthenticationResult"]["AccessToken"]
    except ClientError as e:
        logger.error(f"認証エラー: {e}")
        raise


def compute_stats(latencies: list[float]) -> dict[str, float]:
    """レイテンシーリストから統計値を計算する"""
    if not latencies:
        return {"count": 0, "mean": 0, "median": 0, "p95": 0, "p99": 0, "min": 0, "max": 0}

    sorted_latencies = sorted(latencies)
    count = len(sorted_latencies)
    p95_idx = int(count * 0.95)
    p99_idx = int(count * 0.99)

    return {
        "count": count,
        "mean": round(statistics.mean(sorted_latencies), 3),
        "median": round(statistics.median(sorted_latencies), 3),
        "p95": round(sorted_latencies[min(p95_idx, count - 1)], 3),
        "p99": round(sorted_latencies[min(p99_idx, count - 1)], 3),
        "min": round(min(sorted_latencies), 3),
        "max": round(max(sorted_latencies), 3),
        "stdev": round(statistics.stdev(sorted_latencies), 3) if count > 1 else 0,
    }


def measure_is_authorized(
    client: Any,
    policy_store_id: str,
    principal: dict,
    action: dict,
    resource: dict,
    context: dict | None = None,
) -> tuple[float, bool, str]:
    """
    IsAuthorized API を1回呼び出してレイテンシーを測定する

    Returns:
        (latency_ms, success, decision)
    """
    start = time.perf_counter()
    try:
        params = {
            "policyStoreId": policy_store_id,
            "principal": principal,
            "action": action,
            "resource": resource,
        }
        if context:
            params["context"] = context

        response = client.is_authorized(**params)
        elapsed = (time.perf_counter() - start) * 1000
        decision = response.get("decision", "UNKNOWN")
        return elapsed, True, decision
    except ClientError as e:
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, False, str(e)


def benchmark_cedar_latency(
    config: dict, iterations: int, dry_run: bool = False
) -> dict:
    """Cedar Policy Engine のレイテンシーベンチマークを実行する"""
    results = {
        "benchmark": "cedar-latency",
        "iterations": iterations,
        "warmup_count": WARMUP_COUNT,
        "region": config.get("region", REGION),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenarios": {},
    }

    if dry_run:
        logger.info("[DRY-RUN] Cedar レイテンシーベンチマーク（実際の API 呼び出しはスキップ）")
        for scenario in ["admin_allow", "user_allow", "user_deny", "unknown_principal"]:
            results["scenarios"][scenario] = {
                "stats": compute_stats([1.0 + i * 0.1 for i in range(iterations)]),
                "errors": 0,
                "dry_run": True,
            }
        return results

    client = boto3.client(
        "verifiedpermissions", region_name=config.get("region", REGION)
    )
    policy_store_id = config["policyEngineId"]

    # テストシナリオの定義
    scenarios = {
        "admin_allow": {
            "principal": {
                "entityType": "AgentCore::User",
                "entityId": "admin@tenant-a.example.com",
            },
            "action": {
                "actionType": "AgentCore::Action",
                "actionId": "InvokeTool",
            },
            "resource": {
                "entityType": "AgentCore::Tool",
                "entityId": "financial-data",
            },
        },
        "user_allow": {
            "principal": {
                "entityType": "AgentCore::User",
                "entityId": "user@tenant-a.example.com",
            },
            "action": {
                "actionType": "AgentCore::Action",
                "actionId": "InvokeTool",
            },
            "resource": {
                "entityType": "AgentCore::Tool",
                "entityId": "read-only-data",
            },
        },
        "user_deny": {
            "principal": {
                "entityType": "AgentCore::User",
                "entityId": "user@tenant-a.example.com",
            },
            "action": {
                "actionType": "AgentCore::Action",
                "actionId": "InvokeTool",
            },
            "resource": {
                "entityType": "AgentCore::Tool",
                "entityId": "admin-only-tool",
            },
        },
        "unknown_principal": {
            "principal": {
                "entityType": "AgentCore::User",
                "entityId": "unknown@unknown.example.com",
            },
            "action": {
                "actionType": "AgentCore::Action",
                "actionId": "InvokeTool",
            },
            "resource": {
                "entityType": "AgentCore::Tool",
                "entityId": "some-tool",
            },
        },
    }

    total_iterations = WARMUP_COUNT + iterations
    for scenario_name, params in scenarios.items():
        logger.info(f"[START] シナリオ: {scenario_name} ({total_iterations} 回)")
        latencies = []
        errors = 0

        for i in range(total_iterations):
            latency, success, decision = measure_is_authorized(
                client,
                policy_store_id,
                params["principal"],
                params["action"],
                params["resource"],
            )

            # ウォームアップ期間はスキップ
            if i < WARMUP_COUNT:
                continue

            if success:
                latencies.append(latency)
            else:
                errors += 1
                if errors <= 3:
                    logger.warning(f"  エラー #{errors}: {decision}")

        stats = compute_stats(latencies)
        results["scenarios"][scenario_name] = {
            "stats": stats,
            "errors": errors,
        }
        logger.info(
            f"  [OK] 平均: {stats['mean']:.1f}ms, "
            f"中央値: {stats['median']:.1f}ms, "
            f"P95: {stats['p95']:.1f}ms, "
            f"P99: {stats['p99']:.1f}ms, "
            f"エラー: {errors}"
        )

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Cedar Policy Engine レイテンシーベンチマーク"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1000,
        help="測定回数（ウォームアップ除く、デフォルト: 1000）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ダミーデータで実行（API 呼び出しなし）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="結果の出力先ファイル（デフォルト: 標準出力）",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Cedar Policy Engine レイテンシーベンチマーク")
    logger.info("=" * 60)
    logger.info(f"  測定回数: {args.iterations}")
    logger.info(f"  ウォームアップ: {WARMUP_COUNT}")
    logger.info(f"  Dry-run: {args.dry_run}")

    config = load_config()
    results = benchmark_cedar_latency(config, args.iterations, args.dry_run)

    output_json = json.dumps(results, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        logger.info(f"[OK] 結果を保存しました: {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
