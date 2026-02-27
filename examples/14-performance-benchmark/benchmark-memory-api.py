#!/usr/bin/env python3
"""
Memory API レイテンシーベンチマーク

Memory API の CRUD 操作のレイテンシーを測定する。
PutMemoryRecord, RetrieveMemoryRecords, DeleteMemoryRecord の
各操作のパフォーマンスとバッチサイズの影響を計測する。

前提条件:
- Memory リソースが作成済み
- IAM Role が設定済み
- phase14-config.json が存在する

Usage:
  python3 benchmark-memory-api.py
  python3 benchmark-memory-api.py --iterations 200
  python3 benchmark-memory-api.py --dry-run

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
import uuid

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

WARMUP_COUNT = 10


def load_config() -> dict:
    """phase14-config.json を読み込む"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"設定ファイルが見つかりません: {CONFIG_FILE}")
        logger.info("Hint: phase14-config.json.example をコピーして設定してください")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    required_fields = ["region", "memoryId"]
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


def create_memory_client(config: dict):
    """Memory API クライアントを作成する"""
    return boto3.client(
        "bedrock-agentcore-memory",
        region_name=config.get("region", REGION),
    )


def measure_put_memory_record(
    client, memory_id: str, namespace: str, content: str, actor_id: str
) -> tuple[float, bool]:
    """PutMemoryRecord のレイテンシーを測定する"""
    start = time.perf_counter()
    try:
        client.put_memory_record(
            memoryId=memory_id,
            namespace=namespace,
            actorId=actor_id,
            content={
                "text": content,
            },
        )
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, True
    except ClientError:
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, False


def measure_retrieve_memory_records(
    client, memory_id: str, namespace: str, query: str
) -> tuple[float, bool, int]:
    """RetrieveMemoryRecords のレイテンシーを測定する"""
    start = time.perf_counter()
    try:
        response = client.retrieve_memory_records(
            memoryId=memory_id,
            namespace=namespace,
            query=query,
        )
        elapsed = (time.perf_counter() - start) * 1000
        records = response.get("memoryRecords", [])
        return elapsed, True, len(records)
    except ClientError:
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, False, 0


def measure_delete_memory_record(
    client, memory_id: str, record_id: str
) -> tuple[float, bool]:
    """DeleteMemoryRecord のレイテンシーを測定する"""
    start = time.perf_counter()
    try:
        client.delete_memory_record(
            memoryId=memory_id,
            memoryRecordId=record_id,
        )
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, True
    except ClientError:
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, False


def benchmark_memory_api(
    config: dict, iterations: int, dry_run: bool = False
) -> dict:
    """Memory API のレイテンシーベンチマークを実行する"""
    results = {
        "benchmark": "memory-api",
        "iterations": iterations,
        "warmup_count": WARMUP_COUNT,
        "region": config.get("region", REGION),
        "memory_id": config["memoryId"],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenarios": {},
    }

    batch_sizes = [1, 10, 50]

    if dry_run:
        logger.info("[DRY-RUN] Memory API ベンチマーク（実際の API 呼び出しはスキップ）")
        for scenario in [
            "put_single",
            "retrieve_single",
            "delete_single",
            "put_batch_10",
            "put_batch_50",
            "retrieve_batch_10",
            "retrieve_batch_50",
        ]:
            results["scenarios"][scenario] = {
                "stats": compute_stats([5.0 + i * 0.1 for i in range(iterations)]),
                "errors": 0,
                "dry_run": True,
            }
        return results

    client = create_memory_client(config)
    memory_id = config["memoryId"]
    namespace = f"benchmark-{uuid.uuid4().hex[:8]}"
    actor_id = "benchmark-user"

    total_iterations = WARMUP_COUNT + iterations

    # --- シナリオ 1: PutMemoryRecord (単一) ---
    logger.info(f"[START] PutMemoryRecord (単一) ({total_iterations} 回)")
    latencies = []
    errors = 0
    created_records = []

    for i in range(total_iterations):
        content = f"Benchmark test record {i} - {uuid.uuid4().hex[:8]}"
        latency, success = measure_put_memory_record(
            client, memory_id, namespace, content, actor_id
        )
        if i >= WARMUP_COUNT:
            if success:
                latencies.append(latency)
            else:
                errors += 1

    stats = compute_stats(latencies)
    results["scenarios"]["put_single"] = {"stats": stats, "errors": errors}
    logger.info(
        f"  [OK] 平均: {stats['mean']:.1f}ms, 中央値: {stats['median']:.1f}ms, "
        f"P95: {stats['p95']:.1f}ms, P99: {stats['p99']:.1f}ms"
    )

    # 少し待ってから Retrieve を測定（レコードがインデックスされるのを待つ）
    logger.info("  インデックス更新を待機中（5 秒）...")
    time.sleep(5)

    # --- シナリオ 2: RetrieveMemoryRecords (単一クエリ) ---
    logger.info(f"[START] RetrieveMemoryRecords (単一クエリ) ({total_iterations} 回)")
    latencies = []
    errors = 0
    queries = [
        "benchmark test record",
        "performance measurement",
        "test data retrieval",
    ]

    for i in range(total_iterations):
        query = queries[i % len(queries)]
        latency, success, count = measure_retrieve_memory_records(
            client, memory_id, namespace, query
        )
        if i >= WARMUP_COUNT:
            if success:
                latencies.append(latency)
            else:
                errors += 1

    stats = compute_stats(latencies)
    results["scenarios"]["retrieve_single"] = {"stats": stats, "errors": errors}
    logger.info(
        f"  [OK] 平均: {stats['mean']:.1f}ms, 中央値: {stats['median']:.1f}ms, "
        f"P95: {stats['p95']:.1f}ms, P99: {stats['p99']:.1f}ms"
    )

    # --- シナリオ 3: バッチ PutMemoryRecord ---
    for batch_size in batch_sizes[1:]:  # 10, 50
        scenario_name = f"put_batch_{batch_size}"
        logger.info(f"[START] PutMemoryRecord (バッチ {batch_size} レコード) ({total_iterations} 回)")
        latencies = []
        errors = 0

        for i in range(total_iterations):
            # バッチ内の各 Put を連続実行してトータル時間を測定
            start = time.perf_counter()
            batch_success = True
            for j in range(batch_size):
                content = f"Batch {i} record {j} - {uuid.uuid4().hex[:8]}"
                try:
                    client.put_memory_record(
                        memoryId=memory_id,
                        namespace=namespace,
                        actorId=actor_id,
                        content={"text": content},
                    )
                except ClientError:
                    batch_success = False
                    break
            elapsed = (time.perf_counter() - start) * 1000

            if i >= WARMUP_COUNT:
                if batch_success:
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

    # --- シナリオ 4: バッチ RetrieveMemoryRecords ---
    for batch_size in batch_sizes[1:]:  # 10, 50
        scenario_name = f"retrieve_batch_{batch_size}"
        logger.info(f"[START] RetrieveMemoryRecords (バッチ {batch_size} クエリ) ({total_iterations} 回)")
        latencies = []
        errors = 0

        for i in range(total_iterations):
            start = time.perf_counter()
            batch_success = True
            for j in range(batch_size):
                query = f"batch {i} record {j}"
                try:
                    client.retrieve_memory_records(
                        memoryId=memory_id,
                        namespace=namespace,
                        query=query,
                    )
                except ClientError:
                    batch_success = False
                    break
            elapsed = (time.perf_counter() - start) * 1000

            if i >= WARMUP_COUNT:
                if batch_success:
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

    # --- クリーンアップ: DeleteMemoryRecord ---
    logger.info(f"[START] DeleteMemoryRecord (単一) ({total_iterations} 回)")
    # まずレコードを取得
    try:
        response = client.retrieve_memory_records(
            memoryId=memory_id,
            namespace=namespace,
            query="benchmark",
        )
        record_ids = [r["memoryRecordId"] for r in response.get("memoryRecords", [])]
    except ClientError:
        record_ids = []

    latencies = []
    errors = 0

    if record_ids:
        for i in range(min(total_iterations, len(record_ids))):
            latency, success = measure_delete_memory_record(
                client, memory_id, record_ids[i]
            )
            if i >= WARMUP_COUNT:
                if success:
                    latencies.append(latency)
                else:
                    errors += 1

    stats = compute_stats(latencies)
    results["scenarios"]["delete_single"] = {"stats": stats, "errors": errors}
    if latencies:
        logger.info(
            f"  [OK] 平均: {stats['mean']:.1f}ms, 中央値: {stats['median']:.1f}ms, "
            f"P95: {stats['p95']:.1f}ms, P99: {stats['p99']:.1f}ms"
        )
    else:
        logger.info("  [WARNING] 削除対象のレコードが見つかりませんでした")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Memory API レイテンシーベンチマーク"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="測定回数（ウォームアップ除く、デフォルト: 100）",
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
    logger.info("Memory API レイテンシーベンチマーク")
    logger.info("=" * 60)
    logger.info(f"  測定回数: {args.iterations}")
    logger.info(f"  ウォームアップ: {WARMUP_COUNT}")
    logger.info(f"  Dry-run: {args.dry_run}")

    config = load_config()
    results = benchmark_memory_api(config, args.iterations, args.dry_run)

    output_json = json.dumps(results, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        logger.info(f"[OK] 結果を保存しました: {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
