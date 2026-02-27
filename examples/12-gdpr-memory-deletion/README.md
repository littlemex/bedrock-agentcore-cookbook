# GDPR Memory Deletion Workflow (Right to Erasure)

> **[注意] E2E テスト未実施**: この Example は Zenn book の技術的主張を検証するためのリファレンス実装です。コードのローカル構文検証は完了していますが、実際の AWS 環境での E2E テストは未実施です。GDPR コンプライアンスに関わるため、本番利用前に必ず実環境での包括的な検証を行ってください。特に、削除の完全性保証（ベクトルストアを含む）の確認が必要です。

GDPR Right to Erasure（忘れられる権利、GDPR 第 17 条）に対応した、
AgentCore Memory レコードの手動削除ワークフローを実装するサンプルです。

## 概要

マルチテナント SaaS 環境で、ユーザーから「忘れられる権利」の行使要求を受けた場合に、
対象ユーザーの全記憶データを安全かつ監査可能な方法で削除します。

### 設計方針

1. **最小権限の原則**: GDPR Processor ロールは削除と検索操作のみ許可。作成・更新は明示的に拒否
2. **バッチ削除**: `BatchDeleteMemoryRecords` API で最大 100 件/リクエストの効率的な削除
3. **監査証跡**: 全削除操作を JSON 監査ログとして記録。CloudTrail ログとの照合も可能
4. **Dry-Run サポート**: 実際に削除せずに対象レコードを確認可能

## E2E テスト

全ステップを自動で実行し、結果を `VERIFICATION_RESULT.md` に出力する:

```bash
./run-e2e-test.sh
```

テスト対象の actor_id を指定する場合:

```bash
./run-e2e-test.sh tenant-a:user-001
```

テスト結果は JSON 形式で `VERIFICATION_RESULT.md` に記録される。
結果テンプレートは `examples/VERIFICATION_RESULT.md.template` を参照。

## ファイル構成

| ファイル | 説明 |
|---------|------|
| `setup-gdpr-processor-role.py` | GDPR Processor IAM ロール作成（削除操作のみ許可） |
| `gdpr-delete-user-memories.py` | ユーザー記憶バッチ削除スクリプト（削除後検証付き） |
| `gdpr-generate-deletion-certificate.py` | 削除証明書生成（JSON 形式） |
| `gdpr-audit-report.py` | 削除監査レポート生成（Markdown 形式） |
| `run-e2e-test.sh` | E2E テストスクリプト (全ステップ自動実行) |
| `phase12-config.json.example` | 設定ファイルテンプレート |

## 前提条件

- AWS CLI 設定済み（`aws configure`）
- AWS アカウントに以下の権限:
  - `iam:CreateRole`
  - `iam:PutRolePolicy`
  - `iam:UpdateAssumeRolePolicy`
  - `sts:AssumeRole`
  - `bedrock-agentcore:BatchDeleteMemoryRecords`
  - `bedrock-agentcore:RetrieveMemoryRecords`
  - `cloudtrail:LookupEvents`（監査レポート生成時）
- Memory リソースが作成済み（`examples/01-memory-api/setup-memory.py` 参照）

## セットアップ

### 1. 設定ファイルの準備

```bash
cp phase12-config.json.example phase12-config.json
```

既存の `phase5-config.json` から Memory 情報をコピーするか、直接編集してください。

### 2. GDPR Processor IAM ロールの作成

```bash
python3 setup-gdpr-processor-role.py
```

このスクリプトは以下を作成します:

- `gdpr-memory-processor-role` IAM ロール
- `GDPRMemoryDeletePolicy` インラインポリシー

**許可される操作:**
- `bedrock-agentcore:BatchDeleteMemoryRecords`（バッチ削除）
- `bedrock-agentcore:DeleteMemoryRecord`（単体削除）
- `bedrock-agentcore:RetrieveMemoryRecords`（検索）
- `bedrock-agentcore:ListMemoryRecords`（一覧）
- `bedrock-agentcore:GetMemoryRecord`（取得）

**明示的に拒否される操作:**
- `bedrock-agentcore:BatchCreateMemoryRecords`（新規作成）
- `bedrock-agentcore:BatchUpdateMemoryRecords`（更新）
- `bedrock-agentcore:CreateMemory`（Memory リソース作成）
- `bedrock-agentcore:DeleteMemory`（Memory リソース削除）
- `bedrock-agentcore:UpdateMemory`（Memory リソース更新）

### 3. ユーザー記憶の削除

```bash
# Dry-Run（削除せずに確認のみ）
python3 gdpr-delete-user-memories.py --actor-id tenant-a:user-001 --dry-run

# 実際に削除
python3 gdpr-delete-user-memories.py --actor-id tenant-a:user-001
```

処理フロー:

1. GDPR Processor ロールに `AssumeRole`
2. `RetrieveMemoryRecords` で対象ユーザーの記憶を全件取得（ページネーション対応）
3. `BatchDeleteMemoryRecords` で最大 100 件ずつバッチ削除
4. 削除後に `RetrieveMemoryRecords` で残存レコードが 0 件であることを検証
5. 削除結果を `audit-reports/` に JSON 監査ログとして保存

### 4. 削除証明書の生成

削除完了後、GDPR コンプライアンス向けの削除証明書を生成します:

```bash
# 監査ログファイルを指定して証明書生成
python3 gdpr-generate-deletion-certificate.py --audit-log audit-reports/gdpr-deletion-tenant_a_user-001-20260227T120000Z.json

# actor_id を指定して最新の監査ログから自動生成
python3 gdpr-generate-deletion-certificate.py --actor-id tenant-a:user-001
```

証明書には以下の情報が含まれます:

- 削除操作の日時と対象 actor_id
- 削除されたレコード件数
- 削除後検証の結果（PASS/FAIL）
- 監査ログファイルの SHA-256 ハッシュ（改ざん検知用）
- GDPR コンプライアンス情報

### 5. 監査レポートの生成

```bash
# 全件レポート
python3 gdpr-audit-report.py

# 特定ユーザーのレポート
python3 gdpr-audit-report.py --actor-id tenant-a:user-001

# CloudTrail 検索をスキップ
python3 gdpr-audit-report.py --skip-cloudtrail
```

## E2E テスト

`run-e2e-test.sh` スクリプトを使用して、セットアップからテスト、監査レポート生成までを一括で実行できます。

```bash
bash run-e2e-test.sh
```

このスクリプトは以下を順番に実行します:

1. GDPR Processor ロールの作成 (`setup-gdpr-processor-role.py`)
2. ユーザー記憶の削除（Dry-Run + 実行） (`gdpr-delete-user-memories.py`)
3. 削除後の残存レコード検証
4. 監査レポート生成 (`gdpr-audit-report.py`)

テスト結果は標準出力に表示されます。削除後の残存レコードが 0 件であれば正常です。

詳細な E2E テスト手順は [E2E_TEST_GUIDE.md](../../E2E_TEST_GUIDE.md) を参照してください。

## IAM ポリシー設計

### GDPR Processor ロールの Trust Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::ACCOUNT_ID:root"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "gdpr-processor"
        }
      }
    }
  ]
}
```

### GDPR Processor ロールの Permission Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowMemoryRecordDeletion",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:BatchDeleteMemoryRecords",
        "bedrock-agentcore:DeleteMemoryRecord"
      ],
      "Resource": "arn:aws:bedrock-agentcore:REGION:ACCOUNT_ID:memory/MEMORY_ID"
    },
    {
      "Sid": "AllowMemoryRecordRetrieval",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:RetrieveMemoryRecords",
        "bedrock-agentcore:ListMemoryRecords",
        "bedrock-agentcore:GetMemoryRecord"
      ],
      "Resource": "arn:aws:bedrock-agentcore:REGION:ACCOUNT_ID:memory/MEMORY_ID"
    },
    {
      "Sid": "DenyMemoryRecordCreationAndUpdate",
      "Effect": "Deny",
      "Action": [
        "bedrock-agentcore:BatchCreateMemoryRecords",
        "bedrock-agentcore:BatchUpdateMemoryRecords"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyMemoryResourceModification",
      "Effect": "Deny",
      "Action": [
        "bedrock-agentcore:CreateMemory",
        "bedrock-agentcore:DeleteMemory",
        "bedrock-agentcore:UpdateMemory"
      ],
      "Resource": "*"
    }
  ]
}
```

## 監査ログ形式

削除操作ごとに `audit-reports/` に JSON ファイルが生成されます:

```json
{
  "gdprAction": "right-to-erasure",
  "timestamp": "2026-02-27T12:00:00Z",
  "actorId": "tenant-a:user-001",
  "dryRun": false,
  "summary": {
    "totalRecordsFound": 150,
    "totalDeleted": 150,
    "totalFailed": 0
  },
  "batches": [
    {
      "batchNumber": 1,
      "recordCount": 100,
      "successCount": 100,
      "failedCount": 0,
      "status": "completed"
    },
    {
      "batchNumber": 2,
      "recordCount": 50,
      "successCount": 50,
      "failedCount": 0,
      "status": "completed"
    }
  ]
}
```

## GDPR コンプライアンスチェックリスト

1. [ ] データ主体からの削除要求を受領・記録
2. [ ] データ主体の本人確認を実施
3. [ ] 対象の全記憶レコードを特定（Dry-Run で確認）
4. [ ] GDPR Processor ロール（最小権限）で削除を実行
5. [ ] 監査ログで削除を確認
6. [ ] CloudTrail イベントを検証
7. [ ] データ主体に完了通知を送信
8. [ ] GDPR の 30 日期限内に完了

## CloudTrail による監査

`BatchDeleteMemoryRecords` の呼び出しは CloudTrail に自動記録されます。
以下の情報が記録されます:

- 実行日時
- 実行者（AssumeRole のセッション情報）
- 削除対象の Memory ID
- ソース IP アドレス

監査レポートスクリプトは CloudTrail ログを自動的に照合します。

## 注意事項

- Memory API のレコード削除は物理削除です。削除後の復元はできません
- Dry-Run モードで対象レコードを事前に確認することを推奨します
- 監査レポートは GDPR コンプライアンスの証拠として最低 3 年間保管してください
- このサンプルは Memory API のみを対象としています。
  S3、DynamoDB 等の他のデータストアに個人データがある場合は別途対応が必要です

### Reflection データ（Level 2）の削除について

AgentCore Memory の Reflection（Level 2）は、個別の記憶レコードから抽出・統合されたユーザーの
嗜好や行動パターンの要約データです。このデータはベクトルストアに保存される場合があります。

**GDPR Right to Erasure を完全に履行するには、以下の点に留意してください:**

1. **Memory API レコードの削除だけでは不十分な場合がある**: Reflection データが別途
   ベクトルストア（Amazon OpenSearch Serverless 等）に保存されている場合、
   Memory API の `BatchDeleteMemoryRecords` では Reflection データが削除されない可能性があります

2. **ベクトルストアの直接削除が必要**: Reflection データの完全削除には、
   ベクトルストアに対する直接的な削除操作が必要になる場合があります。
   使用しているベクトルストアの API（例: OpenSearch の `_delete_by_query`）で
   対象 actor_id に関連するエンベディングを削除してください

3. **削除証明書での記録**: `gdpr-generate-deletion-certificate.py` で生成される証明書の
   `compliance.additionalDataStores` フィールドに、ベクトルストアの削除状況を
   手動で追記することを推奨します

4. **結果整合性に注意**: ベクトルストアの削除は結果整合性（eventual consistency）で
   反映される場合があります。削除後に十分な待機時間を設けてから検証してください

## 参考資料

- [GDPR Article 17 - Right to erasure](https://gdpr-info.eu/art-17-gdpr/)
- [AWS Bedrock AgentCore Memory API ドキュメント](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-memory.html)
- [AWS CloudTrail ユーザーガイド](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/)
