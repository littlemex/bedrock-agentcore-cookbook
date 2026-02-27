# Phase 14: Performance Benchmark

Bedrock AgentCore の各コンポーネントのパフォーマンスを測定するベンチマークスイートです。

## 概要

このベンチマークスイートは以下のコンポーネントのパフォーマンスを測定します:

1. **Cedar Policy Engine** - IsAuthorized API のレイテンシー
2. **DynamoDB AuthPolicyTable** - Query スループット
3. **Memory API** - CRUD 操作のレイテンシー
4. **Interceptor Lambda** - コールドスタート/ウォームスタート

## ディレクトリ構成

```
14-performance-benchmark/
  README.md                       - このファイル
  phase14-config.json.example     - 設定ファイルテンプレート
  benchmark-cedar-latency.py      - Cedar Policy Engine ベンチマーク
  benchmark-dynamodb-throughput.py - DynamoDB スループットベンチマーク
  benchmark-memory-api.py         - Memory API ベンチマーク
  benchmark-interceptor-lambda.py - Interceptor Lambda ベンチマーク
  run-all-benchmarks.sh           - 全ベンチマーク統合実行スクリプト
  BENCHMARK_RESULTS.md.template   - 結果テンプレート
```

## 前提条件

- Python 3.10+
- boto3 がインストール済み
- AWS 認証情報が設定済み
- 以下のリソースがデプロイ済み:
  - Gateway + Policy Engine（Phase 3-4）
  - Memory リソース（Phase 1）
  - DynamoDB AuthPolicyTable（Phase 13）
  - Interceptor Lambda（Phase 7）

## セットアップ

1. 設定ファイルを作成:

```bash
cp phase14-config.json.example phase14-config.json
```

2. 設定ファイルを編集して実際のリソース ID を記入:

```bash
vi phase14-config.json
```

## 使い方

### 全ベンチマーク一括実行

```bash
# 全ベンチマーク実行
./run-all-benchmarks.sh

# ドライランモード（API 呼び出しなし）
./run-all-benchmarks.sh --dry-run

# 測定回数を指定
./run-all-benchmarks.sh --iterations 500

# 出力先を指定
./run-all-benchmarks.sh --output-dir ./my-results
```

### 個別ベンチマーク実行

```bash
# Cedar Policy Engine
python3 benchmark-cedar-latency.py --iterations 1000

# DynamoDB
python3 benchmark-dynamodb-throughput.py --iterations 1000

# Memory API
python3 benchmark-memory-api.py --iterations 100

# Interceptor Lambda
python3 benchmark-interceptor-lambda.py --iterations 1000
```

### 共通オプション

| オプション | 説明 | デフォルト |
|-----------|------|----------|
| `--iterations N` | 測定回数（ウォームアップ除く） | 1000 (Memory API は 100) |
| `--dry-run` | ダミーデータで実行（API 呼び出しなし） | 無効 |
| `--output FILE` | 結果の出力先ファイル（JSON） | 標準出力 |

## 各ベンチマークの詳細

### benchmark-cedar-latency.py

Cedar Policy Engine の `IsAuthorized` API のレイテンシーを測定します。

**測定シナリオ:**
- `admin_allow` - admin ユーザーの許可リクエスト
- `user_allow` - 一般ユーザーの許可リクエスト
- `user_deny` - 一般ユーザーの拒否リクエスト
- `unknown_principal` - 未知ユーザーのリクエスト

### benchmark-dynamodb-throughput.py

AuthPolicyTable への Query スループットを測定します。

**測定シナリオ:**
- `get_item_email_pk` - Email Primary Key での GetItem
- `query_tenant_gsi` - TenantId GSI での Query
- `batch_get_10/50/100` - バッチサイズ別の BatchGetItem

### benchmark-memory-api.py

Memory API の CRUD 操作のレイテンシーを測定します。

**測定シナリオ:**
- `put_single` - 単一レコードの PutMemoryRecord
- `retrieve_single` - 単一クエリの RetrieveMemoryRecords
- `delete_single` - 単一レコードの DeleteMemoryRecord
- `put_batch_10/50` - バッチサイズ別の連続 PutMemoryRecord
- `retrieve_batch_10/50` - バッチサイズ別の連続 RetrieveMemoryRecords

### benchmark-interceptor-lambda.py

Gateway Interceptor Lambda のパフォーマンスを測定します。

**測定シナリオ:**
- `request_interceptor_warm` - Request Interceptor ウォームスタート
- `request_interceptor_cold` - Request Interceptor コールドスタート
- `response_interceptor_warm` - Response Interceptor ウォームスタート
- `memory_128mb/256mb/512mb` - メモリサイズ別の実行時間

**[注意]** コールドスタート測定は Lambda の設定を変更してコールドスタートを強制します。
メモリサイズ測定は Lambda のメモリサイズを変更しますが、測定完了後に元の値に復元します。

## 期待されるベースライン値

| コンポーネント | メトリクス | 目標値 |
|--------------|----------|--------|
| Cedar IsAuthorized | 平均レイテンシー | < 50ms |
| Cedar IsAuthorized | P95 レイテンシー | < 100ms |
| Cedar IsAuthorized | P99 レイテンシー | < 200ms |
| DynamoDB GetItem (PK) | 平均レイテンシー | < 10ms |
| DynamoDB Query (GSI) | 平均レイテンシー | < 20ms |
| DynamoDB BatchGetItem (100) | 平均レイテンシー | < 50ms |
| Memory PutRecord | 平均レイテンシー | < 100ms |
| Memory RetrieveRecords | 平均レイテンシー | < 200ms |
| Memory DeleteRecord | 平均レイテンシー | < 100ms |
| Lambda ウォームスタート | 平均レイテンシー | < 20ms |
| Lambda コールドスタート | 平均レイテンシー | < 500ms |

## 出力形式

### JSON 出力

各ベンチマークスクリプトは JSON 形式で結果を出力します:

```json
{
  "benchmark": "cedar-latency",
  "iterations": 1000,
  "warmup_count": 10,
  "region": "us-east-1",
  "timestamp": "2026-02-27T00:00:00Z",
  "scenarios": {
    "admin_allow": {
      "stats": {
        "count": 1000,
        "mean": 45.2,
        "median": 42.1,
        "p95": 85.3,
        "p99": 120.5,
        "min": 15.0,
        "max": 250.3,
        "stdev": 20.1
      },
      "errors": 0
    }
  }
}
```

### CSV 出力

`run-all-benchmarks.sh` は CSV サマリーファイルも生成します:

```csv
benchmark,scenario,count,mean_ms,median_ms,p95_ms,p99_ms,min_ms,max_ms,stdev_ms,errors
cedar-latency,admin_allow,1000,45.2,42.1,85.3,120.5,15.0,250.3,20.1,0
```

### Markdown レポート

`run-all-benchmarks.sh` は結果を BENCHMARK_RESULTS.md にまとめます。
テンプレートは BENCHMARK_RESULTS.md.template を参照してください。

## 測定方法

- `time.perf_counter()` を使用して高精度なレイテンシーを測定
- 最初の 10 回はウォームアップとして統計から除外
- 各測定は最低 100 回以上実行
- 統計値: 平均、中央値、P95、P99、最小、最大、標準偏差
- エラー数も記録
