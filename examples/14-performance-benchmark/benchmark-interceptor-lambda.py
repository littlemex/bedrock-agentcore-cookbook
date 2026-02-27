#!/usr/bin/env python3
"""
Gateway Interceptor Lambda ベンチマーク

Gateway Interceptor Lambda のコールドスタート・ウォームスタートを測定する。
Request Interceptor と Response Interceptor の比較、
メモリサイズ（128MB, 256MB, 512MB）での測定を行う。

前提条件:
- Interceptor Lambda がデプロイ済み
- phase14-config.json が存在する

Usage:
  python3 benchmark-interceptor-lambda.py
  python3 benchmark-interceptor-lambda.py --iterations 200
  python3 benchmark-interceptor-lambda.py --dry-run

環境変数:
  AWS_DEFAULT_REGION: AWS リージョン（デフォルト: us-east-1）
"""

import argparse
import base64
import json
import logging
import os
import statistics
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
CONFIG_FILE = os.path.join(SCRIPT_DIR, "phase14-config.json")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

WARMUP_COUNT = 10

# テスト用メモリサイズ（MB）
MEMORY_SIZES = [128, 256, 512]


def load_config() -> dict:
    """phase14-config.json を読み込む"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"設定ファイルが見つかりません: {CONFIG_FILE}")
        logger.info("Hint: phase14-config.json.example をコピーして設定してください")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    required_fields = ["region", "interceptorFunctionName"]
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


def create_mock_jwt(role="user", tenant_id="tenant-a", user_id="user-1"):
    """テスト用の JWT トークンを生成する"""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()

    payload = base64.urlsafe_b64encode(
        json.dumps({
            "sub": user_id,
            "role": role,
            "tenant_id": tenant_id,
            "client_id": "test-client-id",
            "token_use": "access",
        }).encode()
    ).rstrip(b"=").decode()

    signature = base64.urlsafe_b64encode(b"test-signature").rstrip(b"=").decode()
    return f"Bearer {header}.{payload}.{signature}"


def create_request_interceptor_event(role="admin", tool_name="financial-data"):
    """Request Interceptor 用テストイベントを生成する"""
    return {
        "mcp": {
            "gatewayRequest": {
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"query": "benchmark test"},
                },
            },
            "headers": {
                "authorization": create_mock_jwt(role=role),
            },
        },
    }


def create_response_interceptor_event():
    """Response Interceptor 用テストイベントを生成する"""
    return {
        "mcp": {
            "gatewayResponse": {
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Benchmark response data for performance testing",
                        }
                    ],
                },
            },
            "gatewayRequest": {
                "method": "tools/call",
                "params": {
                    "name": "test-tool",
                },
            },
            "headers": {
                "authorization": create_mock_jwt(role="admin"),
            },
        },
    }


def invoke_lambda(
    lambda_client, function_name: str, payload: dict
) -> tuple[float, bool, dict]:
    """Lambda を Invoke してレイテンシーを測定する"""
    start = time.perf_counter()
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode(),
        )
        elapsed = (time.perf_counter() - start) * 1000

        response_payload = json.loads(response["Payload"].read())
        init_duration = response.get("LogResult", "")

        return elapsed, True, {
            "status_code": response["StatusCode"],
            "response": response_payload,
        }
    except ClientError as e:
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, False, {"error": str(e)}


def force_cold_start(lambda_client, function_name: str):
    """環境変数を更新してコールドスタートを強制する"""
    try:
        lambda_client.update_function_configuration(
            FunctionName=function_name,
            Environment={
                "Variables": {
                    "BENCHMARK_TIMESTAMP": str(time.time()),
                }
            },
        )
        # 設定変更が反映されるまで少し待機
        time.sleep(3)
    except ClientError as e:
        logger.warning(f"コールドスタート強制に失敗: {e}")


def update_memory_size(lambda_client, function_name: str, memory_mb: int):
    """Lambda のメモリサイズを更新する"""
    try:
        lambda_client.update_function_configuration(
            FunctionName=function_name,
            MemorySize=memory_mb,
        )
        # 設定変更が反映されるまで待機
        waiter = lambda_client.get_waiter("function_updated_v2")
        waiter.wait(FunctionName=function_name)
        logger.info(f"  メモリサイズを {memory_mb}MB に更新しました")
    except ClientError as e:
        logger.warning(f"メモリサイズ更新に失敗: {e}")
    except Exception as e:
        logger.warning(f"メモリサイズ更新待機に失敗: {e}")
        time.sleep(5)


def benchmark_interceptor_lambda(
    config: dict, iterations: int, dry_run: bool = False
) -> dict:
    """Interceptor Lambda のベンチマークを実行する"""
    results = {
        "benchmark": "interceptor-lambda",
        "iterations": iterations,
        "warmup_count": WARMUP_COUNT,
        "region": config.get("region", REGION),
        "function_name": config["interceptorFunctionName"],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenarios": {},
    }

    if dry_run:
        logger.info("[DRY-RUN] Interceptor Lambda ベンチマーク（実際の API 呼び出しはスキップ）")
        scenarios = [
            "request_interceptor_warm",
            "request_interceptor_cold",
            "response_interceptor_warm",
            "memory_128mb",
            "memory_256mb",
            "memory_512mb",
        ]
        for scenario in scenarios:
            base = 50.0 if "cold" in scenario else 5.0
            results["scenarios"][scenario] = {
                "stats": compute_stats([base + i * 0.1 for i in range(iterations)]),
                "errors": 0,
                "dry_run": True,
            }
        return results

    region = config.get("region", REGION)
    lambda_client = boto3.client("lambda", region_name=region)
    function_name = config["interceptorFunctionName"]

    total_iterations = WARMUP_COUNT + iterations

    # 元のメモリサイズを記録（後でリストアする）
    try:
        func_config = lambda_client.get_function_configuration(
            FunctionName=function_name
        )
        original_memory = func_config.get("MemorySize", 256)
    except ClientError:
        original_memory = 256

    # --- シナリオ 1: Request Interceptor (ウォームスタート) ---
    logger.info(f"[START] Request Interceptor ウォームスタート ({total_iterations} 回)")
    latencies = []
    errors = 0

    for i in range(total_iterations):
        event = create_request_interceptor_event(role="admin")
        latency, success, resp = invoke_lambda(lambda_client, function_name, event)
        if i >= WARMUP_COUNT:
            if success:
                latencies.append(latency)
            else:
                errors += 1

    stats = compute_stats(latencies)
    results["scenarios"]["request_interceptor_warm"] = {"stats": stats, "errors": errors}
    logger.info(
        f"  [OK] 平均: {stats['mean']:.1f}ms, 中央値: {stats['median']:.1f}ms, "
        f"P95: {stats['p95']:.1f}ms, P99: {stats['p99']:.1f}ms"
    )

    # --- シナリオ 2: Request Interceptor (コールドスタート) ---
    cold_start_iterations = min(iterations, 20)  # コールドスタートは回数を抑える
    logger.info(f"[START] Request Interceptor コールドスタート ({cold_start_iterations} 回)")
    latencies = []
    errors = 0

    for i in range(cold_start_iterations):
        # コールドスタートを強制
        force_cold_start(lambda_client, function_name)

        event = create_request_interceptor_event(role="admin")
        latency, success, resp = invoke_lambda(lambda_client, function_name, event)
        if success:
            latencies.append(latency)
        else:
            errors += 1

    stats = compute_stats(latencies)
    results["scenarios"]["request_interceptor_cold"] = {
        "stats": stats,
        "errors": errors,
        "note": "Each invocation forced a cold start via config update",
    }
    if latencies:
        logger.info(
            f"  [OK] 平均: {stats['mean']:.1f}ms, 中央値: {stats['median']:.1f}ms, "
            f"P95: {stats['p95']:.1f}ms, P99: {stats['p99']:.1f}ms"
        )

    # --- シナリオ 3: Response Interceptor (ウォームスタート) ---
    logger.info(f"[START] Response Interceptor ウォームスタート ({total_iterations} 回)")
    latencies = []
    errors = 0

    for i in range(total_iterations):
        event = create_response_interceptor_event()
        latency, success, resp = invoke_lambda(lambda_client, function_name, event)
        if i >= WARMUP_COUNT:
            if success:
                latencies.append(latency)
            else:
                errors += 1

    stats = compute_stats(latencies)
    results["scenarios"]["response_interceptor_warm"] = {"stats": stats, "errors": errors}
    logger.info(
        f"  [OK] 平均: {stats['mean']:.1f}ms, 中央値: {stats['median']:.1f}ms, "
        f"P95: {stats['p95']:.1f}ms, P99: {stats['p99']:.1f}ms"
    )

    # --- シナリオ 4-6: メモリサイズ別 ---
    for memory_mb in MEMORY_SIZES:
        scenario_name = f"memory_{memory_mb}mb"
        logger.info(f"[START] メモリサイズ {memory_mb}MB ({total_iterations} 回)")

        update_memory_size(lambda_client, function_name, memory_mb)

        latencies = []
        errors = 0

        for i in range(total_iterations):
            event = create_request_interceptor_event(role="admin")
            latency, success, resp = invoke_lambda(lambda_client, function_name, event)
            if i >= WARMUP_COUNT:
                if success:
                    latencies.append(latency)
                else:
                    errors += 1

        stats = compute_stats(latencies)
        results["scenarios"][scenario_name] = {
            "stats": stats,
            "errors": errors,
            "memory_mb": memory_mb,
        }
        logger.info(
            f"  [OK] 平均: {stats['mean']:.1f}ms, 中央値: {stats['median']:.1f}ms, "
            f"P95: {stats['p95']:.1f}ms, P99: {stats['p99']:.1f}ms"
        )

    # メモリサイズを元に戻す
    logger.info(f"メモリサイズを元の値 ({original_memory}MB) に復元中...")
    update_memory_size(lambda_client, function_name, original_memory)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Gateway Interceptor Lambda ベンチマーク"
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
    logger.info("Gateway Interceptor Lambda ベンチマーク")
    logger.info("=" * 60)
    logger.info(f"  測定回数: {args.iterations}")
    logger.info(f"  ウォームアップ: {WARMUP_COUNT}")
    logger.info(f"  Dry-run: {args.dry_run}")

    config = load_config()
    results = benchmark_interceptor_lambda(config, args.iterations, args.dry_run)

    output_json = json.dumps(results, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        logger.info(f"[OK] 結果を保存しました: {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
