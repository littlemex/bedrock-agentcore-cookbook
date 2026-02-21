# AWS Bedrock AgentCore Cookbook

AWS Bedrock AgentCore の実装パターンとベストプラクティスを集めた Cookbook です。

## 概要

このリポジトリには、AWS Bedrock AgentCore の主要な機能の実装例とデプロイスクリプトが含まれています。各例は独立して動作し、実際の E2E 検証に基づいて作成されています。

## AgentCore とは

AWS Bedrock AgentCore は、AI エージェントの開発を簡素化するためのサービスです。以下の機能を提供します：

- **Memory API**: エージェントの会話履歴とコンテキストの永続化
- **Gateway**: MCP サーバーやカスタムツールの統合
- **Policy Engine**: Cedar Policy 言語によるアクセス制御
- **IAM ABAC**: 属性ベースのきめ細かなアクセス制御

## ディレクトリ構成

```
bedrock-agentcore-cookbook/
├── README.md                   # このファイル
├── requirements.txt            # 共通の Python 依存パッケージ
├── .gitignore
└── examples/
    ├── 01-memory-api/          # Memory API の基本的な使い方
    ├── 02-iam-abac/            # IAM ABAC の実装パターン
    ├── 03-gateway/             # Gateway のデプロイと設定
    ├── 04-policy-engine/       # Policy Engine + Cedar Policy
    ├── 05-end-to-end/          # 全コンポーネントの E2E 統合テスト
    ├── 06-response-interceptor/ # Response Interceptor (RBAC ツールフィルタリング)
    ├── 07-request-interceptor/  # Request Interceptor (RBAC ツール認可)
    └── 08-outbound-auth/        # Outbound Auth (OAuth2/API Key)
```

## 前提条件

- AWS CLI 設定済み（`aws configure`）
- Python 3.9+
- AWS アカウントに適切な権限（各例の README を参照）

## セットアップ

1. リポジトリのクローン

```bash
git clone https://github.com/YOUR_ORG/bedrock-agentcore-cookbook.git
cd bedrock-agentcore-cookbook
```

2. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

## 使い方

各例は独立して動作しますが、以下の順序で実行することを推奨します：

### 1. Memory API の基本

Memory API を使用して、エージェントの会話履歴を永続化します。

```bash
cd examples/01-memory-api
python setup-memory.py
```

詳細: [examples/01-memory-api/README.md](examples/01-memory-api/README.md)

### 2. IAM ABAC の実装

Memory API に対する IAM ABAC（属性ベースアクセス制御）を実装します。

```bash
cd examples/02-iam-abac
python setup-iam-roles.py
python test-h1-condition-key.py
```

詳細: [examples/02-iam-abac/README.md](examples/02-iam-abac/README.md)

### 3. Gateway のデプロイ

MCP サーバーやカスタムツールを統合するための Gateway をデプロイします。

```bash
cd examples/03-gateway
python deploy-gateway.py
```

詳細: [examples/03-gateway/README.md](examples/03-gateway/README.md)

### 4. Policy Engine + Cedar Policy

Gateway に対するアクセス制御を Cedar Policy で実装します。

```bash
cd examples/04-policy-engine
python create-policy-engine.py
python associate-policy-engine.py
python put-cedar-policies.py
```

詳細: [examples/04-policy-engine/README.md](examples/04-policy-engine/README.md)

### 5. E2E 統合テスト

全コンポーネントを統合した E2E テストを実行します。

```bash
cd examples/05-end-to-end
python test-phase5.py
```

詳細: [examples/05-end-to-end/README.md](examples/05-end-to-end/README.md)

### 6. Response Interceptor

Gateway の Response Interceptor を使用して、MCP サーバーのレスポンスを RBAC でフィルタリングします。

```bash
cd examples/06-response-interceptor
python3 verify-response-interceptor.py        # ローカル検証
python3 deploy-response-interceptor.py        # Lambda デプロイ + Gateway 設定
python3 verify-response-interceptor.py --remote  # リモート検証
```

詳細: [examples/06-response-interceptor/README.md](examples/06-response-interceptor/README.md)

### 7. Request Interceptor

Gateway の Request Interceptor を使用して、MCP サーバーへのリクエストを RBAC で認可します。

```bash
cd examples/07-request-interceptor
python3 verify-request-interceptor.py        # ローカル検証
python3 deploy-request-interceptor.py        # Lambda デプロイ + Gateway 設定
python3 verify-request-interceptor.py --remote  # リモート検証
```

詳細: [examples/07-request-interceptor/README.md](examples/07-request-interceptor/README.md)

### 8. Outbound Auth

Gateway の Outbound Auth 機能を使用して、外部サービスへの認証情報を管理します。

```bash
cd examples/08-outbound-auth
python3 verify-outbound-auth.py
```

詳細: [examples/08-outbound-auth/README.md](examples/08-outbound-auth/README.md)

## 重要な発見事項

このリポジトリの例は、実際の E2E 検証を通じて得られた知見に基づいています。主な発見事項：

### 1. bedrock-agentcore: namespace Condition Key

AWS 公式ドキュメントには記載されていませんが、`bedrock-agentcore: namespace` Condition Key は**実際に動作します**。マルチテナント環境でのアクセス制御に非常に有効です。

### 2. Cedar Policy の resource 制約

Cedar Policy では、resource にワイルドカード（`resource` のみ）を使用できません。最低でも `resource is AgentCore::Gateway` が必要です。

### 3. Policy Engine の命名規則

Policy Engine 名とポリシー名は `^[A-Za-z][A-Za-z0-9_]*$` パターンに従う必要があります。**ハイフンは使用できません**。

### 4. API パラメータの命名規則

boto3 の `bedrock-agentcore-control` クライアントでは、以下のようなパラメータ名の違いがあります：

- Gateway API: `gatewayIdentifier` (get), `name` (create)
- Target API: `targetId` (get), `name` (create)
- Policy Engine API: `policyEngineId` (get), `name` (create)

詳細は各例の README を参照してください。

## トラブルシューティング

### Error: 'AgentsforBedrockRuntime' object has no attribute 'create_gateway'

**原因**: 間違った boto3 クライアントを使用している

**解決策**: `bedrock-agentcore-control` クライアントを使用してください

```python
client = boto3.client('bedrock-agentcore-control', region_name='us-east-1')
```

### Error: Unknown parameter 'gatewayId'

**原因**: API パラメータ名が間違っている

**解決策**: `gatewayId` → `gatewayIdentifier` に変更してください

### Error: Policy Engine name validation error

**原因**: Policy Engine 名にハイフンが含まれている

**解決策**: アンダースコアを使用してください（例: `my_policy_engine`）

## クリーンアップ

各例には `cleanup.py` スクリプトが含まれています。作成したリソースを削除するには：

```bash
cd examples/01-memory-api
python cleanup.py

cd ../02-iam-abac
# IAM Role とポリシーを手動で削除

cd ../03-gateway
python cleanup.py

cd ../04-policy-engine
# Policy Engine とポリシーを手動で削除
```

## 制限事項

### 未検証項目

以下の項目は、現時点では未検証です：

- `PartiallyAuthorizeActions` API での実動作確認（boto3/AWS CLI 未サポート）
- Policy Engine mode=ENFORCE での動作確認

### 検証済み項目（Phase 7 で追加）

以下の項目は、2026-02-21 の Phase 7 検証で確認済みです：

- Response Interceptor: Lambda デプロイ + Gateway 設定 + リモート呼び出し（7 PASS local / 4 PASS remote）
- Request Interceptor: Lambda デプロイ + Gateway 設定 + リモート呼び出し（11 PASS local / 4 PASS remote）
- Gateway Outbound Auth: OAuth2 (25 ベンダー) + API Key の CRUD（9 PASS / 0 FAIL）

### AWS リージョン

このリポジトリの例は、`us-east-1` リージョンで検証されています。他のリージョンでは動作が異なる可能性があります。

## 貢献

プルリクエストや Issue は歓迎します。

## ライセンス

MIT License

## 参考資料

- [AWS Bedrock AgentCore 公式ドキュメント](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
- [AWS Bedrock AgentCore 公式サンプル](https://github.com/aws-samples/amazon-bedrock-agentcore-samples)
- [Cedar Policy Language](https://www.cedarpolicy.com/)
- [Model Context Protocol (MCP)](https://github.com/anthropics/model-context-protocol)

## 関連プロジェクト

- [AWS Bedrock AgentCore Verification Book](https://github.com/YOUR_ORG/agentcore-verification) - このリポジトリの検証結果をまとめた Zenn book
