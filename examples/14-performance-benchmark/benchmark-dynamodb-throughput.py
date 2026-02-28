#!/usr/bin/env python3
"""
DynamoDB AuthPolicyTable スループットベンチマーク

AuthPolicyTable への Query スループットを測定する。
Email PK クエリと TenantId GSI クエリの比較、バッチサイズごとの
パフォーマンスを計測する。

前提条件:
- AuthPolicyTable が作成済み
- テストデータが投入済み（seed-test-users.py）
- phase14-config.json が存在する

Usage:
  python3 benchmark-dynamodb-throughput.py
  python3 benchmark-dynamodb-throughput.py --iterations 200
  python3 benchmark-dynamodb-throughput.py --dry-run

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
    from boto3.dynamodb.conditions import Key
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

WARMUP_COUNT = 10


def load_config() -> dict:
    """phase14-config.json を読み込む"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"設定ファイルが見つかりません: {CONFIG_FILE}")
        logger.info("Hint: phase14-config.json.example をコピーして設定してください")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    required_fields = ["region", "tableName"]
    missing = [f for f in required_fields if f not in config]
    if missing:
        logger.error(f"設定ファイルに必須フィールドがありません: {missing}")
        sys.exit(1)

    return config


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


def measure_get_item(table: Any, email: str) -> tuple[float, bool]:
    """GetItem (Email PK) のレイテンシーを測定する"""
    start = time.perf_counter()
    try:
        response = table.get_item(Key={"email": email})
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, "Item" in response
    except ClientError:
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, False


def measure_query_by_tenant(table: Any, tenant_id: str) -> tuple[float, bool, int]:
    """Query (TenantId GSI) のレイテンシーを測定する"""
    start = time.perf_counter()
    try:
        response = table.query(
            IndexName="TenantIdIndex",
            KeyConditionExpression=Key("tenant_id").eq(tenant_id),
        )
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, True, response.get("Count", 0)
    except ClientError:
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, False, 0


def measure_batch_get(dynamodb_resource: Any, table_name: str, emails: list[str]) -> tuple[float, bool, int]:
    """BatchGetItem のレイテンシーを測定する"""
    keys = [{"email": email} for email in emails]
    start = time.perf_counter()
    try:
        response = dynamodb_resource.batch_get_item(
            RequestItems={
                table_name: {
                    "Keys": keys,
                }
            }
        )
        elapsed = (time.perf_counter() - start) * 1000
        items = response.get("Responses", {}).get(table_name, [])
        return elapsed, True, len(items)
    except ClientError:
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, False, 0


def generate_test_emails(count: int) -> list[str]:
    """テスト用メールアドレスリストを生成する"""
    tenants = ["tenant-a", "tenant-b", "tenant-c"]
    roles = ["admin", "user", "viewer"]
    emails = []
    for i in range(count):
        tenant = tenants[i % len(tenants)]
        role = roles[i % len(roles)]
        emails.append(f"{role}-{i}@{tenant}.example.com")
    return emails


def benchmark_dynamodb_throughput(
    config: dict, iterations: int, dry_run: bool = False
) -> dict:
    """DynamoDB スループットベンチマークを実行する"""
    results = {
        "benchmark": "dynamodb-throughput",
        "iterations": iterations,
        "warmup_count": WARMUP_COUNT,
        "region": config.get("region", REGION),
        "table_name": config["tableName"],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenarios": {},
    }

    if dry_run:
        logger.info("[DRY-RUN] DynamoDB スループットベンチマーク（実際の API 呼び出しはスキップ）")
        scenarios = [
            "get_item_email_pk",
            "query_tenant_gsi",
            "batch_get_10",
            "batch_get_50",
            "batch_get_100",
        ]
        for scenario in scenarios:
            results["scenarios"][scenario] = {
                "stats": compute_stats([2.0 + i * 0.05 for i in range(iterations)]),
                "errors": 0,
                "dry_run": True,
            }
        return results

    region = config.get("region", REGION)
    table_name = config["tableName"]
    dynamodb = boto3.resource("dynamodb", region_name=region)
    dynamodb_client = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    # テスト用メールアドレスとテナント
    test_emails = [
        "admin@tenant-a.example.com",
        "user@tenant-a.example.com",
        "viewer@tenant-a.example.com",
    ]
    test_tenants = ["tenant-a", "tenant-b"]

    total_iterations = WARMUP_COUNT + iterations

    # --- シナリオ 1: GetItem (Email PK) ---
    logger.info(f"[START] GetItem (Email PK) ({total_iterations} 回)")
    latencies = []
    errors = 0
    for i in range(total_iterations):
        email = test_emails[i % len(test_emails)]
        latency, success = measure_get_item(table, email)
        if i >= WARMUP_COUNT:
            if success:
                latencies.append(latency)
            else:
                errors += 1

    stats = compute_stats(latencies)
    results["scenarios"]["get_item_email_pk"] = {"stats": stats, "errors": errors}
    logger.info(
        f"  [OK] 平均: {stats['mean']:.1f}ms, 中央値: {stats['median']:.1f}ms, "
        f"P95: {stats['p95']:.1f}ms, P99: {stats['p99']:.1f}ms"
    )

    # --- シナリオ 2: Query (TenantId GSI) ---
    logger.info(f"[START] Query (TenantId GSI) ({total_iterations} 回)")
    latencies = []
    errors = 0
    for i in range(total_iterations):
        tenant = test_tenants[i % len(test_tenants)]
        latency, success, count = measure_query_by_tenant(table, tenant)
        if i >= WARMUP_COUNT:
            if success:
                latencies.append(latency)
            else:
                errors += 1

    stats = compute_stats(latencies)
    results["scenarios"]["query_tenant_gsi"] = {"stats": stats, "errors": errors}
    logger.info(
        f"  [OK] 平均: {stats['mean']:.1f}ms, 中央値: {stats['median']:.1f}ms, "
        f"P95: {stats['p95']:.1f}ms, P99: {stats['p99']:.1f}ms"
    )

    # --- シナリオ 3-5: BatchGetItem (バッチサイズ: 10, 50, 100) ---
    batch_sizes = [10, 50, 100]
    for batch_size in batch_sizes:
        scenario_name = f"batch_get_{batch_size}"
        logger.info(f"[START] BatchGetItem (サイズ: {batch_size}) ({total_iterations} 回)")

        # バッチ用のメールアドレスを生成
        batch_emails = generate_test_emails(batch_size)

        latencies = []
        errors = 0

        # DynamoDB BatchGetItem は最大 100 アイテムまで
        effective_batch = batch_emails[:min(batch_size, 100)]

        for i in range(total_iterations):
            # BatchGetItem は boto3.resource 経由で呼ぶ
            start = time.perf_counter()
            try:
                response = dynamodb_client.meta.client.batch_get_item(
                    RequestItems={
                        table_name: {
                            "Keys": [{"email": {"S": e}} for e in effective_batch],
                        }
                    }
                )
                elapsed = (time.perf_counter() - start) * 1000
                success = True
            except Exception:
                elapsed = (time.perf_counter() - start) * 1000
                success = False

            if i >= WARMUP_COUNT:
                if success:
                    latencies.append(elapsed)
                else:
                    errors += 1

        stats = compute_stats(latencies)
        results["scenarios"][scenario_name] = {
            "stats": stats,
            "errors": errors,
            "batch_size": batch_size,
        }
        logger.info(
            f"  [OK] 平均: {stats['mean']:.1f}ms, 中央値: {stats['median']:.1f}ms, "
            f"P95: {stats['p95']:.1f}ms, P99: {stats['p99']:.1f}ms"
        )

    return results


def main():
    parser = argparse.ArgumentParser(
        description="DynamoDB AuthPolicyTable スループットベンチマーク"
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
    logger.info("DynamoDB AuthPolicyTable スループットベンチマーク")
    logger.info("=" * 60)
    logger.info(f"  測定回数: {args.iterations}")
    logger.info(f"  ウォームアップ: {WARMUP_COUNT}")
    logger.info(f"  Dry-run: {args.dry_run}")

    config = load_config()
    results = benchmark_dynamodb_throughput(config, args.iterations, args.dry_run)

    output_json = json.dumps(results, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        logger.info(f"[OK] 結果を保存しました: {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
