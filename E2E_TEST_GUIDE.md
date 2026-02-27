# E2E テストガイド

本ガイドでは、bedrock-agentcore-cookbook の各 Example に対する E2E テストの実行方法を説明します。

---

## テストの目的と範囲

### 目的

- 各 Example のスクリプトが実際の AWS 環境で正常に動作することを検証する
- マルチテナント環境でのアクセス制御（ABAC, Cedar Policy, IAM）が設計通りに機能することを確認する
- セキュリティレビューで検出された問題の改善が有効であることを検証する

### 範囲

| カテゴリ | 対象 Example | 検証内容 |
|----------|-------------|----------|
| 基盤機能 | 01-05 | Memory API, IAM ABAC, Gateway, Cedar Policy, E2E 統合 |
| Interceptor | 06-07 | Response/Request Interceptor の RBAC フィルタリング |
| 認証認可 | 08-10 | Outbound Auth, E2E Auth, Auth Cookbook |
| セキュリティ検証 | 11-13 | S3 ABAC, GDPR 削除, AuthPolicyTable |
| パフォーマンス | 14 | ベンチマーク測定 |
| ResourceTag ABAC | 15 | Memory ResourceTag ベースのテナント分離 |

---

## 前提条件

### AWS 認証情報

以下の AWS 認証情報が設定されていること:

```bash
# 環境変数での設定
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1

# または AWS CLI プロファイルの設定
aws configure --profile agentcore-test
export AWS_PROFILE=agentcore-test
```

### リージョン設定

全テストは `us-east-1` リージョンでの実行を推奨します。他のリージョンでは AgentCore の一部機能が利用できない可能性があります。

### 必要な権限

テスト実行用の IAM ユーザー/ロールには以下の権限が必要です:

- `bedrock-agentcore:*` -- AgentCore 全操作
- `iam:CreateRole`, `iam:PutRolePolicy`, `iam:DeleteRole` -- IAM ロール管理
- `sts:AssumeRole`, `sts:TagSession` -- STS 操作
- `s3:*` -- S3 操作（Example 11）
- `dynamodb:*` -- DynamoDB 操作（Example 13）
- `lambda:*` -- Lambda 操作（Example 06, 07, 09, 10）
- `cloudtrail:LookupEvents` -- 監査レポート（Example 12）

### Python 環境

```bash
cd bedrock-agentcore-cookbook
pip install -r requirements.txt
```

---

## テスト実行手順

### Example 01: Memory API の基本

Memory API の CRUD 操作を検証します。

```bash
cd examples/01-memory-api
python3 setup-memory.py
```

**期待結果**: Memory リソースが作成され、レコードの作成・取得・検索が成功する

**検証項目**:
- [ ] Memory リソースの作成成功
- [ ] メモリレコードの作成（BatchCreateMemoryRecords）
- [ ] メモリレコードの取得（RetrieveMemoryRecords）

---

### Example 02: IAM ABAC

`bedrock-agentcore:namespace` Condition Key を使用した ABAC を検証します。

```bash
cd examples/02-iam-abac
python3 setup-iam-roles.py
python3 test-h1-condition-key.py
```

**期待結果**: 同一テナントのリソースにのみアクセス可能。クロステナントアクセスは拒否される

**検証項目**:
- [ ] Tenant A が自身の namespace にアクセス成功
- [ ] Tenant A が Tenant B の namespace にアクセス拒否（AccessDenied）

---

### Example 03: Gateway のデプロイ

MCP Gateway のデプロイと設定を検証します。

```bash
cd examples/03-gateway
python3 deploy-gateway.py
```

**期待結果**: Gateway が作成され、ステータスが ACTIVE になる

**検証項目**:
- [ ] Gateway の作成成功
- [ ] Gateway ステータスが ACTIVE
- [ ] Target の追加成功

---

### Example 04: Policy Engine + Cedar Policy

Cedar Policy Engine の作成とポリシー適用を検証します。

```bash
cd examples/04-policy-engine
python3 create-policy-engine.py
python3 associate-policy-engine.py
python3 put-cedar-policies.py
```

**期待結果**: Policy Engine が作成され、Cedar ポリシーが適用される

**検証項目**:
- [ ] Policy Engine の作成成功（名前はアンダースコアのみ使用）
- [ ] Gateway との関連付け成功
- [ ] Cedar ポリシーの登録成功

---

### Example 05: E2E 統合テスト

全コンポーネントを統合した E2E テストを実行します。

```bash
cd examples/05-end-to-end
python3 test-phase5.py
```

**期待結果**: Memory API + IAM ABAC + Gateway + Cedar Policy の統合動作が確認される

**検証項目**:
- [ ] STS SessionTags による AssumeRole 成功
- [ ] Namespace ベースの Memory アクセス制御
- [ ] Gateway 経由のツール実行

---

### Example 06: Response Interceptor

Response Interceptor による RBAC フィルタリングを検証します。

```bash
cd examples/06-response-interceptor
# ローカル検証
python3 verify-response-interceptor.py

# Lambda デプロイ + Gateway 設定
python3 deploy-response-interceptor.py

# リモート検証
python3 verify-response-interceptor.py --remote
```

**期待結果**: MCP レスポンスから権限のないツールがフィルタリングされる

**検証項目**:
- [ ] ローカル検証: 7 PASS
- [ ] リモート検証: 4 PASS
- [ ] admin ロールは全ツール表示
- [ ] user ロールは許可ツールのみ表示

---

### Example 07: Request Interceptor

Request Interceptor による RBAC 認可を検証します。

```bash
cd examples/07-request-interceptor
# ローカル検証
python3 verify-request-interceptor.py

# Lambda デプロイ + Gateway 設定
python3 deploy-request-interceptor.py

# リモート検証
python3 verify-request-interceptor.py --remote
```

**期待結果**: 権限のないツール実行がブロックされる

**検証項目**:
- [ ] ローカル検証: 11 PASS
- [ ] リモート検証: 4 PASS
- [ ] 許可されたツール実行は成功
- [ ] 未許可ツール実行はブロック

---

### Example 08: Outbound Auth

OAuth2/API Key による外部サービス認証を検証します。

```bash
cd examples/08-outbound-auth
python3 verify-outbound-auth.py
```

**期待結果**: OAuth2（25 ベンダー）と API Key の CRUD が成功する

**検証項目**:
- [ ] OAuth2 設定の作成・取得・削除: 9 PASS
- [ ] API Key 設定の CRUD

---

### Example 09: E2E 認証認可テスト

Lambda Authorizer + Cedar + ABAC の 4 層 Defense in Depth を検証します。

```bash
cd examples/09-e2e-auth-test
./run-e2e-verification.sh us-east-1 my-test-project
```

**期待結果**: 4 層すべてが連携して動作する

**検証項目**:
- [ ] Lambda Authorizer の認証成功/失敗
- [ ] Cedar Policy の認可判定
- [ ] Gateway Interceptor のフィルタリング
- [ ] IAM ABAC のアクセス制御

---

### Example 10: 認証認可実装サンプル

Auth Cookbook の各コンポーネントの動作を検証します。

```bash
cd examples/10-auth-cookbook
# 各コンポーネントの個別検証は README.md を参照
```

**検証項目**:
- [ ] Lambda Authorizer のデプロイ
- [ ] Pre Token Generation Lambda の動作
- [ ] Cedar ポリシーの適用

---

### Example 11: S3 ABAC

S3 オブジェクトタグベースの ABAC を検証します。

```bash
cd examples/11-s3-abac

# 1. S3 バケットとオブジェクトタグのセットアップ
python3 setup-s3-buckets.py

# 2. IAM ロールの作成
python3 setup-iam-roles.py

# 3. ABAC テストの実行
python3 test-s3-abac.py

# E2E テストの実行（上記 1-3 を一括実行）
bash run-e2e-test.sh
```

**期待結果**: 同一テナントのオブジェクトのみアクセス可能

**検証項目**:
- [ ] Tenant A が自身のオブジェクトにアクセス成功
- [ ] Tenant B が自身のオブジェクトにアクセス成功
- [ ] Tenant A が Tenant B のオブジェクトにアクセス拒否
- [ ] Tenant B が Tenant A のオブジェクトにアクセス拒否

**クリーンアップ**:

```bash
python3 cleanup-s3-resources.py
```

---

### Example 12: GDPR Memory 削除

GDPR Right to Erasure（忘れられる権利）の削除ワークフローを検証します。

```bash
cd examples/12-gdpr-memory-deletion

# 1. 設定ファイルの準備
cp phase12-config.json.example phase12-config.json

# 2. GDPR Processor ロールの作成
python3 setup-gdpr-processor-role.py

# 3. Dry-Run で確認
python3 gdpr-delete-user-memories.py --actor-id tenant-a:user-001 --dry-run

# 4. 実際に削除
python3 gdpr-delete-user-memories.py --actor-id tenant-a:user-001

# 5. 監査レポート生成
python3 gdpr-audit-report.py

# E2E テストの実行（上記 2-5 を一括実行）
bash run-e2e-test.sh
```

**期待結果**: 対象ユーザーの全記憶レコードが削除され、監査ログが生成される

**検証項目**:
- [ ] GDPR Processor ロールの作成成功
- [ ] Dry-Run で対象レコードの一覧取得
- [ ] BatchDeleteMemoryRecords による削除成功
- [ ] 削除後の残存レコード 0 件検証
- [ ] 監査ログの生成
- [ ] 削除証明書の生成

---

### Example 13: AuthPolicyTable

DynamoDB 認証ポリシーテーブルの作成とクエリを検証します。

```bash
cd examples/13-auth-policy-table

# 1. 設定ファイルの準備
cp phase13-config.json.example phase13-config.json

# 2. DynamoDB テーブル作成
python3 setup-dynamodb-table.py

# 3. テストデータ投入
python3 seed-test-users.py

# 4. クエリ検証
python3 query-user-policy.py --email admin@tenant-a.example.com
python3 query-user-policy.py --tenant tenant-a
python3 query-user-policy.py --email admin@tenant-a.example.com --simulate-claims

# E2E テストの実行（上記 2-4 を一括実行）
bash run-e2e-test.sh
```

**期待結果**: テーブルが作成され、Email/TenantId でのクエリが成功する

**検証項目**:
- [ ] DynamoDB テーブル作成成功（PAY_PER_REQUEST）
- [ ] GSI（TenantIdIndex）の作成成功
- [ ] テストデータの投入成功
- [ ] Email による GetItem 成功
- [ ] TenantId による GSI Query 成功
- [ ] Pre Token Generation Lambda クレーム生成シミュレーション

---

### Example 14: パフォーマンスベンチマーク

各コンポーネントのレイテンシーとスループットを測定します。

```bash
cd examples/14-performance-benchmark
# スクリプトの詳細は examples/14-performance-benchmark/README.md を参照
```

**期待結果**: [PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md) に記載のベースライン値を満たす

---

### Example 15: Memory ResourceTag ABAC

Memory リソースに対する `aws:ResourceTag/tenant_id` Condition Key の動作を検証します。

```bash
cd examples/15-memory-resource-tag-abac

# 1. Memory 作成とタグ付与
python3 setup-memory-with-tags.py

# 2. IAM ロール作成
python3 setup-iam-roles-with-resource-tag.py

# 3. IAM ポリシー伝播待機（推奨）
sleep 10

# 4. テスト実行
python3 test-resource-tag-abac.py
```

**期待結果**: 同一テナントの Memory のみアクセス可能。クロステナントアクセスと未タグ付きリソースへのアクセスが拒否される

**検証項目**:
- [ ] Tenant A が自身の Memory にアクセス成功
- [ ] Tenant B が自身の Memory にアクセス成功
- [ ] Tenant A が Tenant B の Memory にアクセス拒否（ResourceTag 不一致）
- [ ] Tenant B が Tenant A の Memory にアクセス拒否（ResourceTag 不一致）
- [ ] ResourceTag なしの Memory へのアクセス拒否（Null Condition 検証）

**クリーンアップ**:

```bash
python3 cleanup-resources.py
```

**注意事項**:
- `aws:ResourceTag/tenant_id` が Memory API で動作しない場合は、代替案として `bedrock-agentcore:namespace`（Example 02）またはテナント別 Memory + Resource ARN 制限パターンを検討してください
- テスト結果は `VERIFICATION_RESULT.md` に自動出力されます

---

## テスト実行順序（推奨）

依存関係を考慮した推奨実行順序:

```
Phase 1: 基盤構築
  01-memory-api → 02-iam-abac → 03-gateway → 04-policy-engine

Phase 2: 統合テスト
  05-end-to-end

Phase 3: Interceptor 検証
  06-response-interceptor → 07-request-interceptor

Phase 4: 認証認可
  08-outbound-auth → 09-e2e-auth-test → 10-auth-cookbook

Phase 5: セキュリティ検証
  11-s3-abac → 12-gdpr-memory-deletion → 13-auth-policy-table

Phase 6: ResourceTag ABAC 検証
  15-memory-resource-tag-abac

Phase 7: パフォーマンス測定
  14-performance-benchmark
```

---

## トラブルシューティング

### 共通エラー

#### `botocore.exceptions.NoCredentialsError`

**原因**: AWS 認証情報が設定されていない

**解決策**:
```bash
aws configure
# または環境変数を設定
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
```

#### `botocore.exceptions.ClientError: AccessDeniedException`

**原因**: IAM 権限が不足している

**解決策**: 前提条件セクションに記載の権限を IAM ユーザー/ロールに付与してください。

#### `botocore.exceptions.EndpointConnectionError`

**原因**: リージョン設定が不正、または AgentCore が利用できないリージョンを指定している

**解決策**:
```bash
export AWS_DEFAULT_REGION=us-east-1
```

### Example 固有のエラー

#### Example 04: `Policy Engine name validation error`

**原因**: Policy Engine 名にハイフンが含まれている

**解決策**: アンダースコアのみを使用してください（例: `my_policy_engine`）

#### Example 11: `s3:ExistingObjectTag condition check failed`

**原因**: S3 オブジェクトタグが設定されていない、またはタグ値が不一致

**解決策**: `setup-s3-buckets.py` を再実行してオブジェクトタグを確認してください。

#### Example 12: `sts:AssumeRole failed for gdpr-processor role`

**原因**: GDPR Processor ロールの Trust Policy が正しく設定されていない

**解決策**: `setup-gdpr-processor-role.py` を再実行して Trust Policy を確認してください。ExternalId には `gdpr-processor` を使用します。

#### Example 13: `Table already exists`

**原因**: 同名のテーブルが既に存在する

**解決策**: 既存テーブルを削除するか、`phase13-config.json` でテーブル名を変更してください。

#### Example 15: `aws:ResourceTag condition check failed` / `AccessDeniedException`

**原因**: Memory リソースにタグが設定されていない、またはタグ値が不一致

**解決策**: `setup-memory-with-tags.py` を再実行して Memory リソースのタグを確認してください。`ListTagsForResource` でタグが正しく付与されているか検証します。`aws:ResourceTag/tenant_id` が Memory API でサポートされていない場合は、README.md の「BLOCKED の場合の代替案」セクションを参照してください。

---

## CI/CD への統合

### GitHub Actions での実行例

```yaml
name: E2E Tests
on:
  workflow_dispatch:
  schedule:
    - cron: '0 9 * * 1'  # 毎週月曜 9:00 UTC

jobs:
  e2e-test:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::ACCOUNT_ID:role/e2e-test-role
          aws-region: us-east-1

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run Example 11 E2E Test
        run: |
          cd examples/11-s3-abac
          bash run-e2e-test.sh

      - name: Run Example 12 E2E Test
        run: |
          cd examples/12-gdpr-memory-deletion
          bash run-e2e-test.sh

      - name: Run Example 13 E2E Test
        run: |
          cd examples/13-auth-policy-table
          bash run-e2e-test.sh

      - name: Run Example 15 ResourceTag ABAC Test
        run: |
          cd examples/15-memory-resource-tag-abac
          python3 setup-memory-with-tags.py
          python3 setup-iam-roles-with-resource-tag.py
          sleep 10
          python3 test-resource-tag-abac.py
```

### 注意事項

- E2E テストは実際の AWS リソースを作成・削除するため、テスト用の AWS アカウントを使用することを推奨します
- テスト完了後は必ずクリーンアップスクリプトを実行してください
- 並列実行時はリソース名の衝突に注意してください
- IAM ロール作成後は伝播に最大 10 秒程度かかる場合があります

---

**作成日**: 2026-02-27
**対象バージョン**: bedrock-agentcore-cookbook v1.0
