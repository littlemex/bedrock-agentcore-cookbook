# End-to-End Integration Test

このディレクトリには、AWS Bedrock AgentCore の全コンポーネントを統合した E2E テストスクリプトが含まれています。

## 概要

このテストスクリプトは、以下のコンポーネントを統合して動作を検証します：

- Memory API
- IAM ABAC（Attribute-Based Access Control）
- Gateway
- Policy Engine + Cedar Policy
- Cognito JWT Authorizer

## ファイル構成

- `test-phase5.py` - E2E 統合テストスクリプト
- `phase5-config.json` - 設定ファイル（リソース ID、ARN など）

## 前提条件

以下のコンポーネントがデプロイ済みであること：

1. **Memory API** (`01-memory-api` を参照)
   - Memory リソース
   - IAM Role とポリシー

2. **IAM ABAC** (`02-iam-abac` を参照)
   - ABAC 用 IAM Role
   - Condition Key を使用した IAM Policy

3. **Gateway** (`03-gateway` を参照)
   - Gateway リソース
   - Lambda Target
   - Cognito JWT Authorizer

4. **Policy Engine** (`04-policy-engine` を参照)
   - Policy Engine リソース
   - Cedar Policy（admin_policy, user_policy）

## セットアップ

1. 依存パッケージのインストール

```bash
pip install -r ../../requirements.txt
```

2. 設定ファイルの準備

`phase5-config.json` を以下の内容で作成してください：

```json
{
  "memoryId": "YOUR_MEMORY_ID",
  "gatewayId": "YOUR_GATEWAY_ID",
  "gatewayArn": "YOUR_GATEWAY_ARN",
  "policyEngineId": "YOUR_POLICY_ENGINE_ID",
  "cognitoUserPoolId": "YOUR_USER_POOL_ID",
  "cognitoAppClientId": "YOUR_APP_CLIENT_ID"
}
```

各値は、前の手順で作成したリソースの ID や ARN を指定します。

3. テストの実行

```bash
python test-phase5.py
```

## テスト内容

### 1. Memory API + IAM ABAC

- namespace=tenant-a でタグ付けされた Memory へのアクセス
- namespace=tenant-b でタグ付けされた Memory へのアクセス（拒否を期待）
- `bedrock-agentcore: namespace` Condition Key の検証

### 2. Gateway + Policy Engine

- Cognito ユーザーの作成（role=admin, role=user）
- JWT トークンの生成
- `PartiallyAuthorizeActions` API を使用したアクセス制御の検証
  - role=admin: 全ツールへのアクセス許可
  - role=user: 特定ツールのみアクセス許可

### 3. Cedar Policy の評価

- Policy Engine mode=LOG_ONLY での動作確認
- Policy Engine mode=ENFORCE での動作確認
- hasTag()/getTag() 構文の実動作検証

## 期待される結果

### Memory API + IAM ABAC

```
[OK] tenant-a Memory へのアクセス: 成功
[NG] tenant-b Memory へのアクセス: AccessDeniedException（期待通り）
```

### Gateway + Policy Engine（LOG_ONLY mode）

```
[OK] role=admin での全ツールアクセス: 成功
[OK] role=user での特定ツールアクセス: 成功
[LOG] role=user での制限ツールアクセス: 成功（ログに記録）
```

### Gateway + Policy Engine（ENFORCE mode）

```
[OK] role=admin での全ツールアクセス: 成功
[OK] role=user での特定ツールアクセス: 成功
[NG] role=user での制限ツールアクセス: AccessDeniedException（期待通り）
```

## トラブルシューティング

### Error: Memory not found

**原因**: Memory が作成されていない、または ID が間違っている

**解決策**: `01-memory-api/setup-memory.py` を実行して Memory を作成してください

### Error: Gateway not found

**原因**: Gateway が作成されていない、または ID が間違っている

**解決策**: `03-gateway/deploy-gateway.py` を実行して Gateway を作成してください

### Error: Invalid JWT token

**原因**: Cognito ユーザーが作成されていない、またはトークンの有効期限が切れている

**解決策**:
1. Cognito User Pool でユーザーを作成
2. スクリプトを再実行して新しいトークンを生成

### Error: Policy evaluation failed

**原因**: Cedar Policy が登録されていない、または構文エラーがある

**解決策**: `04-policy-engine/put-cedar-policies.py` を実行して Cedar Policy を登録してください

## 注意事項

### JWT トークンの有効期限

Cognito JWT トークンには有効期限があります（デフォルト: 1 時間）。テストを実行する際は、毎回新しいトークンを生成することを推奨します。

### Policy Engine のモード

- **LOG_ONLY**: デバッグ用。ポリシー評価はログに記録されますが、アクセスは常に許可されます
- **ENFORCE**: 本番用。ポリシー評価に基づいてアクセスが制御されます

初回テストでは LOG_ONLY モードを使用し、ポリシーが正しく動作することを確認してから ENFORCE モードに切り替えることを推奨します。

## 参考資料

- [AWS Bedrock AgentCore 公式ドキュメント](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
- [Cedar Policy Language](https://www.cedarpolicy.com/)
- [Cognito User Pools](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools.html)
