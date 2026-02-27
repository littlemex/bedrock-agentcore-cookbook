# パフォーマンスベースライン

各コンポーネントの期待されるパフォーマンス指標を記載します。

---

## 概要

AWS Bedrock AgentCore の認証認可アーキテクチャ（4 層 Defense in Depth）における各コンポーネントのレイテンシーとスループットのベースライン値です。

本ドキュメントの値は、`us-east-1` リージョンでの測定に基づく期待値です。実環境ではネットワーク条件、アカウント制限、リソース設定により変動する場合があります。

---

## Cedar Policy Engine

### レイテンシー

| 項目 | LOG_ONLY モード | ENFORCE モード | 備考 |
|------|---------------|---------------|------|
| 単一ポリシー評価 | < 5ms | < 5ms | Cedar のローカル評価 |
| 10 ポリシー評価 | < 10ms | < 10ms | ポリシー数に比例 |
| Gateway 統合オーバーヘッド | < 50ms | < 50ms | API コール含む |

### LOG_ONLY vs ENFORCE の違い

- **LOG_ONLY**: ポリシー評価結果をログに記録するが、アクセスは常に許可する。開発・テスト環境での使用を推奨
- **ENFORCE**: ポリシー評価結果に基づき、アクセスを実際に許可/拒否する。本番環境での使用を推奨

**パフォーマンスへの影響**: 評価ロジック自体は同一のため、レイテンシーの差はほぼない。ただし ENFORCE モードでは拒否レスポンスの生成が追加される。

---

## Memory API

### CRUD 操作レイテンシー

| 操作 | 期待レイテンシー | 備考 |
|------|-----------------|------|
| `BatchCreateMemoryRecords` (10 件) | < 500ms | バッチサイズに依存 |
| `BatchCreateMemoryRecords` (100 件) | < 2000ms | 最大 100 件/リクエスト |
| `RetrieveMemoryRecords` | < 200ms | セマンティック検索 |
| `ListMemoryRecords` | < 100ms | ページネーション付き |
| `GetMemoryRecord` | < 50ms | 単一レコード取得 |
| `BatchDeleteMemoryRecords` (100 件) | < 1000ms | 最大 100 件/リクエスト |

### スループット

| 項目 | 期待値 | 備考 |
|------|--------|------|
| 書き込みスループット | 100 レコード/秒 | バッチ API 使用時 |
| 読み取りスループット | 50 リクエスト/秒 | RetrieveMemoryRecords |
| 削除スループット | 100 レコード/秒 | BatchDeleteMemoryRecords |

---

## DynamoDB AuthPolicyTable

### レイテンシー

| 操作 | 期待レイテンシー | 備考 |
|------|-----------------|------|
| GetItem (Email PK) | < 10ms | 単一キー検索 |
| Query (TenantIdIndex GSI) | < 20ms | GSI 検索、結果件数に依存 |
| PutItem | < 10ms | 単一レコード書き込み |
| Scan (全件) | < 100ms | テストデータ規模（< 100 件）の場合 |

### スループット（PAY_PER_REQUEST モード）

| 項目 | 期待値 | 備考 |
|------|--------|------|
| 読み取りスループット | 自動スケーリング | オンデマンドキャパシティ |
| 書き込みスループット | 自動スケーリング | オンデマンドキャパシティ |
| バーストキャパシティ | 最大 4,000 RCU | アカウントのデフォルト制限 |

### Pre Token Generation Lambda での使用パターン

```
Cognito トークン発行
  → Pre Token Generation Lambda 起動
    → DynamoDB GetItem (< 10ms)
    → カスタムクレーム生成 (< 1ms)
  → Lambda 実行合計: < 50ms（ウォームスタート時）
```

---

## Gateway Interceptor Lambda

### コールドスタート / ウォームスタート

| 項目 | コールドスタート | ウォームスタート | 備考 |
|------|----------------|-----------------|------|
| Response Interceptor | < 1000ms | < 100ms | Python 3.12 ランタイム |
| Request Interceptor | < 1000ms | < 100ms | Python 3.12 ランタイム |
| Lambda Authorizer | < 1500ms | < 200ms | JWT 検証 + JWKS 取得含む |
| Pre Token Generation | < 1000ms | < 50ms | DynamoDB GetItem 含む |

### コールドスタート最適化

- **Provisioned Concurrency**: 常時起動インスタンスを確保することで、コールドスタートを回避
- **Lambda SnapStart**: Java ランタイムの場合に有効（Python は未対応）
- **メモリサイズ**: 256MB 以上を推奨。CPU リソースもメモリに比例して割り当てられる

### ウォームスタート維持

Lambda は約 15 分間リクエストがない場合にコールドスタートが発生します。以下の対策を検討:

1. CloudWatch Events で定期的な keep-alive リクエスト
2. Provisioned Concurrency の設定
3. トラフィックパターンに基づく Auto Scaling 設定

---

## 4 層 Defense in Depth 合計レイテンシー

### レイテンシーの内訳

```
クライアントリクエスト
  │
  ├─ Layer 1: Lambda Authorizer     < 200ms（ウォーム）/ < 1500ms（コールド）
  │   └─ JWT 検証 + JWKS キャッシュ
  │
  ├─ Layer 2: Cedar Policy Engine   < 50ms
  │   └─ ポリシー評価（LOG_ONLY）
  │
  ├─ Layer 3: Request Interceptor   < 100ms（ウォーム）/ < 1000ms（コールド）
  │   └─ ツール認可チェック
  │
  └─ Layer 4: IAM ABAC              < 10ms
      └─ IAM ポリシー評価（AWS 内部）
```

### 合計レイテンシー

| シナリオ | 期待レイテンシー | 備考 |
|----------|-----------------|------|
| 全層ウォームスタート | < 360ms | 通常運用時 |
| Layer 1 コールドスタート | < 1860ms | Lambda Authorizer の初回起動 |
| Layer 3 コールドスタート | < 1360ms | Request Interceptor の初回起動 |
| 全層コールドスタート（最悪ケース） | < 2860ms | 全 Lambda のコールドスタート |

### レイテンシー目標

| 環境 | P50 目標 | P99 目標 | 備考 |
|------|---------|---------|------|
| 開発環境 | < 500ms | < 3000ms | コールドスタート許容 |
| ステージング環境 | < 400ms | < 1500ms | Provisioned Concurrency 推奨 |
| 本番環境 | < 400ms | < 800ms | Provisioned Concurrency 必須 |

---

## スケーリング特性

### テナント数 N の影響

| コンポーネント | スケーリング特性 | テナント数 N の影響 |
|--------------|----------------|-------------------|
| Cedar Policy Engine | O(P) | ポリシー数 P に比例。テナント数の直接影響は少ない |
| Memory API (Namespace) | O(1) | Namespace でテナント分離。テナント数の影響は少ない |
| DynamoDB AuthPolicyTable | O(1) | GetItem はテナント数に関係なく一定 |
| IAM ABAC | O(1) | Condition Key 評価はテナント数に関係なく一定 |
| Lambda Authorizer | O(1) | JWT 検証はテナント数に関係なく一定 |

### Cedar ポリシー数の影響

| ポリシー数 | 評価レイテンシー増加 | 推奨事項 |
|-----------|-------------------|----------|
| 1-10 | 無視可能 | デフォルト構成 |
| 10-100 | < 10ms 増加 | ポリシーのグループ化を検討 |
| 100-1000 | < 50ms 増加 | ポリシースライシング（テナントごとのスコープ）を推奨 |

### 同時接続テナント数の影響

| 同時テナント数 | 影響 | 対策 |
|--------------|------|------|
| 1-10 | 影響なし | デフォルト設定で十分 |
| 10-100 | Lambda 同時実行数に注意 | リザーブド同時実行を設定 |
| 100-1000 | スロットリングのリスク | API リクエストクォータの引き上げを申請 |

---

## 測定方法

### ベンチマーク実行

```bash
cd examples/14-performance-benchmark
# 詳細は examples/14-performance-benchmark/README.md を参照
```

### 手動測定

各 Example のスクリプトにはレイテンシー計測用のログ出力が含まれています:

```python
import time

start = time.time()
response = client.retrieve_memory_records(...)
elapsed_ms = (time.time() - start) * 1000
print(f"[PERF] RetrieveMemoryRecords: {elapsed_ms:.1f}ms")
```

### CloudWatch メトリクス

Lambda 関数のパフォーマンスは CloudWatch で確認できます:

- **Duration**: Lambda 実行時間
- **Init Duration**: コールドスタート時の初期化時間
- **Concurrent Executions**: 同時実行数
- **Throttles**: スロットリング回数

---

## 注意事項

- 本ドキュメントの値は期待値であり、SLA ではありません
- 実環境のパフォーマンスは、AWS アカウントのサービスクォータ、ネットワーク条件、VPC 設定等により変動します
- コールドスタートはリクエストパターン（トラフィックの断続性）に大きく依存します
- DynamoDB のオンデマンドモード（PAY_PER_REQUEST）はバーストトラフィックに対応しますが、事前ウォームアップが必要な場合があります
- Cedar Policy Engine は現在 LOG_ONLY モードでの検証が中心です。ENFORCE モードでのパフォーマンスは別途測定が必要です

---

**作成日**: 2026-02-27
**測定環境**: us-east-1, Python 3.12, Lambda 256MB メモリ
