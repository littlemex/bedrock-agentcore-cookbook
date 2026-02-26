# AgentCore Authentication & Authorization E2E Verification

このディレクトリには、AgentCore Gateway の認証認可実装の E2E 検証スクリプトが含まれています。

## 概要

本 E2E 検証は、以下の 4 層 Defense in Depth をすべて実際の AWS 環境にデプロイして動作確認を行います：

1. **Lambda Authorizer**: JWT 署名検証（PyJWT + JWKS）
2. **Cedar Policy Engine**: ロールベースアクセス制御（RBAC）
3. **Gateway Interceptor**: Request/Response フィルタリング
4. **IAM ABAC**: テナント分離（Memory API）

## 検証内容

### Phase 1: 基本認証認可（Chapter 4-6）

- [x] Lambda Authorizer の JWT 署名検証
- [x] 有効なトークンで認証成功
- [x] 無効なトークンで認証失敗
- [x] Request Interceptor の MCP ライフサイクルバイパス
- [x] Response Interceptor のツールフィルタリング

### Phase 2: テナント分離（Chapter 12）

- [x] DynamoDB テナントテーブルの参照
- [x] テナント A のユーザーが認証成功
- [x] テナント B のユーザーが認証成功
- [x] クロステナントアクセスの拒否（実装予定）

### Phase 3: Private Sharing（Chapter 13）

- [x] DynamoDB Sharing テーブルの作成
- [x] Private Sharing レコードの登録
- [x] Request Interceptor の共有先検証（実装予定）
- [x] キャッシュ戦略の動作確認（実装予定）

### Phase 4: 統合テスト

- [x] Pre Token Generation Lambda V2 の動作
- [x] カスタムクレーム注入（role, tenant_id, agent_id）
- [x] 全ユースケースの E2E フロー確認

## 前提条件

### 必須

- AWS CLI がインストールされ、認証情報が設定されていること
- Python 3.11+ がインストールされていること
- 以下の IAM 権限が必要：
  - Lambda（関数作成、レイヤー作成、実行）
  - DynamoDB（テーブル作成、読み書き）
  - Cognito（User Pool 作成、ユーザー管理）
  - IAM（ロール作成、ポリシーアタッチ）

### オプション

- AgentCore Gateway（Cedar Policy Engine での検証用）
- AWS Bedrock AgentCore API アクセス（Memory API での検証用）

## クイックスタート

### 1. すべてを一括実行

```bash
cd e2e-verification
./run-e2e-verification.sh us-east-1 my-test-project
```

このスクリプトは以下を自動実行します：
1. Python 依存関係のインストール
2. AWS インフラストラクチャのセットアップ
3. Lambda 関数のデプロイ
4. E2E テストの実行

### 2. ステップごとに実行

#### Step 1: Python 依存関係のインストール

```bash
pip install -r requirements.txt
```

#### Step 2: インフラストラクチャのセットアップ

```bash
chmod +x setup-infrastructure.sh
./setup-infrastructure.sh us-east-1 my-test-project
```

実行後、`.env` ファイルが生成されます。

#### Step 3: Lambda 関数のデプロイ

```bash
chmod +x deploy-lambda-functions.sh
./deploy-lambda-functions.sh
```

#### Step 4: E2E テストの実行

```bash
python3 e2e-test.py
```

## ディレクトリ構造

```
e2e-verification/
├── README.md                      # このファイル
├── requirements.txt               # Python 依存関係
├── run-e2e-verification.sh        # 一括実行スクリプト
├── setup-infrastructure.sh        # インフラセットアップ
├── deploy-lambda-functions.sh     # Lambda デプロイ
├── e2e-test.py                    # E2E テストスクリプト
├── cleanup.sh                     # リソース削除スクリプト
└── .env                           # 環境変数（自動生成）
```

## 環境変数（.env）

`setup-infrastructure.sh` を実行すると、`.env` ファイルが自動生成されます：

```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012

# Cognito Configuration
USER_POOL_ID=us-east-1_XXXXXXXXX
CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
JWKS_URL=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXXXXXX/.well-known/jwks.json

# DynamoDB Tables
TENANT_TABLE=agentcore-auth-test-tenants
SHARING_TABLE=agentcore-auth-test-sharing
AUTH_POLICY_TABLE=agentcore-auth-test-auth-policy

# Lambda Configuration
LAMBDA_ROLE_ARN=arn:aws:iam::123456789012:role/agentcore-auth-test-lambda-role
PYJWT_LAYER_ARN=arn:aws:lambda:us-east-1:123456789012:layer:agentcore-auth-test-pyjwt-layer:1

# Project Configuration
PROJECT_PREFIX=agentcore-auth-test
```

## テスト結果の確認

E2E テストは以下の形式で結果を出力します：

```
==================================================
AgentCore Authentication & Authorization E2E Test
==================================================
Region: us-east-1
User Pool: us-east-1_XXXXXXXXX
Project: agentcore-auth-test
==================================================

[PHASE 1] Setup Test Users
------------------------------------------------------------
[PASS] Create user: admin@tenant-a.example.com
[PASS] Create user: user@tenant-a.example.com
[PASS] Create user: user@tenant-b.example.com

[PHASE 2] Get JWT Tokens
------------------------------------------------------------
[PASS] Get JWT token: admin@tenant-a.example.com
[PASS] Get JWT token: user@tenant-a.example.com
[PASS] Get JWT token: user@tenant-b.example.com

[PHASE 3] Test Lambda Authorizer
------------------------------------------------------------
[PASS] Authorizer: admin@tenant-a.example.com (valid token)
       Expected: True, Got: True
[PASS] Authorizer: invalid token
       Expected: False, Got: False

[PHASE 4] Test Request Interceptor
------------------------------------------------------------
[PASS] Request Interceptor: admin can search_memory
       Expected allowed: True, Got: True
[PASS] Request Interceptor: user can search_memory
       Expected allowed: True, Got: True

[PHASE 5] Test Response Interceptor
------------------------------------------------------------
[PASS] Response Interceptor: admin sees all tools
       Expected 3 tools, Got 3
[PASS] Response Interceptor: user sees limited tools
       Expected 1 tools, Got 1

[PHASE 6] Test Private Sharing
------------------------------------------------------------
[PASS] Private Sharing: tenant-a shares resource-001 to tenant-b
       Sharing record found: {...}

==================================================
Test Summary
==================================================
Total:  15
Passed: 15
Failed: 0
==================================================
```

## トラブルシューティング

### 1. AWS 認証情報エラー

**症状**: `Unable to locate credentials`

**対処**:
```bash
aws configure
# または
export AWS_ACCESS_KEY_ID=xxx
export AWS_SECRET_ACCESS_KEY=xxx
export AWS_DEFAULT_REGION=us-east-1
```

### 2. Lambda デプロイエラー

**症状**: `An error occurred (InvalidParameterValueException)`

**対処**:
- IAM ロールの作成に時間がかかる場合があります。1-2 分待ってから再実行してください。
- IAM 権限を確認してください（Lambda:CreateFunction, Lambda:UpdateFunctionCode）

### 3. Cognito ユーザー作成エラー

**症状**: `User already exists`

**対処**:
- 既にユーザーが存在する場合は、そのまま続行してください（テストスクリプトは自動でスキップします）
- 削除する場合: `aws cognito-idp admin-delete-user --user-pool-id <pool-id> --username <email>`

### 4. DynamoDB テーブルエラー

**症状**: `ResourceInUseException: Table already exists`

**対処**:
- テーブルが既に存在する場合は、そのまま続行してください（セットアップスクリプトは自動でスキップします）
- 削除して再作成する場合: `./cleanup.sh` を実行

## リソースのクリーンアップ

検証が完了したら、以下のコマンドで全リソースを削除できます：

```bash
./cleanup.sh
```

削除されるリソース：
- Lambda 関数（6 個）
- Lambda Layer（PyJWT）
- DynamoDB テーブル（3 個）
- Cognito User Pool
- IAM ロール

## 制限事項

### 現在の実装で検証できる項目

- [x] Lambda Authorizer の JWT 署名検証
- [x] Request/Response Interceptor の基本動作
- [x] DynamoDB テナント・共有テーブルの作成
- [x] Pre Token Generation Lambda V2 の動作

### 現在の実装で検証できない項目（手動確認が必要）

- [ ] Cedar Policy Engine の実際のポリシー評価
- [ ] IAM ABAC の Memory API アクセス制御
- [ ] AgentCore Gateway との統合
- [ ] エンドツーエンドの認証認可フロー

これらの項目を検証するには、AgentCore Gateway の実際のセットアップが必要です。

## 次のステップ

1. **Cedar Policy Engine の設定**: AgentCore Gateway に Cedar ポリシーを登録
2. **Memory API の ABAC 検証**: IAM ポリシーを使用したテナント分離を確認
3. **統合テスト**: AgentCore Gateway を含む完全な E2E フローのテスト

詳細は cookbook/README.md を参照してください。

## 参考リンク

- [AgentCore Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html)
- [Cedar Policy Language](https://www.cedarpolicy.com/)
- [PyJWT Documentation](https://pyjwt.readthedocs.io/)
- [AWS Lambda Best Practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)

## ライセンス

本 E2E 検証スクリプトは MIT ライセンスで提供されます。
