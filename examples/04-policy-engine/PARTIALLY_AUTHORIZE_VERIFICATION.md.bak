# PartiallyAuthorizeActions API 検証結果

## 検証日時
2026-02-20

## 検証目的
Task #91 の完全完了を目指し、PartiallyAuthorizeActions API の実動作を検証する。

## 検証環境

### デプロイ済みリソース

| リソース | ID | ステータス |
|---------|-----|-----------|
| Gateway | `e2e-phase3-gateway-sytqnigmll` | READY |
| Policy Engine | `e2e_phase3_policy_engine-80kx42tcle` | ACTIVE |
| Policy Engine Mode | LOG_ONLY | - |
| Cognito User Pool | `us-east-1_9V08k9Eiv` | - |
| DynamoDB Table | `AuthPolicyTable` | - |

### Cedar Policy

| ポリシー名 | ID | 内容 |
|-----------|-----|------|
| admin_policy | `admin_policy-ji_7qtsk83` | 全ツールへのアクセスを許可（role=admin）|
| user_policy | `user_policy-2efzhamk9n` | 特定ツールのみ許可（role=user）|

### テストユーザー

| ユーザー名 | Role | Status |
|-----------|------|--------|
| admin-test@example.com | admin | CONFIRMED |
| user-test@example.com | user | CONFIRMED |

## 検証結果

### [OK] 1. Cognito テストユーザーの作成

`setup-cognito-users.py` を使用して、以下のユーザーを作成しました：

- **admin-test@example.com** (role=admin)
- **user-test@example.com** (role=user)

ユーザー情報は Cognito User Pool と DynamoDB (AuthPolicyTable) の両方に登録されています。Pre Token Generation Lambda が JWT クレームに `role` を追加します。

### [OK] 2. JWT トークンの取得

`test-partially-authorize.py` を使用して、Cognito ユーザーの認証に成功しました：

- Admin ユーザー: JWT ID トークン取得成功
- User ユーザー: JWT ID トークン取得成功

### [BLOCKED] 3. PartiallyAuthorizeActions API の呼び出し

**ステータス**: API サポート待ち

**問題点**:
- boto3 1.42.54 では `partially_authorize_actions` メソッドが存在しない
- AWS CLI (`aws bedrock-agentcore-control`) にも `partially-authorize-actions` コマンドが見つからない

**確認したこと**:
- boto3 クライアント: `bedrock-agentcore-control` クライアントは存在する
- API メソッド: `partially_authorize_actions` メソッドは存在しない
- AWS CLI: `bedrock-agentcore-control` サービスは存在するが、authorization 関連のコマンドは見つからない

**推測される原因**:
- PartiallyAuthorizeActions API がまだ boto3/AWS CLI でサポートされていない
- API が Preview/Beta 段階でドキュメントのみ公開されている
- API エンドポイントや命名規則が異なる可能性

## 検証済み項目

以下の検証は完了しました：

- [OK] Gateway のデプロイ
- [OK] Policy Engine のデプロイと Gateway への関連付け
- [OK] Cedar Policy の登録（admin_policy, user_policy）
- [OK] hasTag()/getTag() 構文の Policy Engine での検証
- [OK] resource 制約の要件確認
- [OK] Cognito テストユーザーの作成
- [OK] DynamoDB へのユーザーポリシー情報の登録
- [OK] Pre Token Generation Lambda の動作確認
- [OK] JWT トークンの取得

## 未完了の検証項目

以下の検証は API サポート待ちのため未完了です：

- [BLOCKED] PartiallyAuthorizeActions API での実動作確認
- [BLOCKED] role=admin と role=user での tools/list レスポンス差異の検証
- [BLOCKED] Policy Engine mode=ENFORCE での動作確認

## 代替検証方法

PartiallyAuthorizeActions API が利用可能になるまでの間、以下の代替検証を検討できます：

### 1. CloudWatch Logs での Policy Engine 評価ログの確認

Policy Engine は LOG_ONLY モードで動作しているため、CloudWatch Logs にポリシー評価結果が記録されているはずです。これを確認することで、Cedar Policy が正しく評価されているかを検証できます。

### 2. Gateway へのダイレクトアクセス

Gateway エンドポイントに直接アクセスし、JWT トークンを使用してツールを呼び出すことで、Policy Engine の動作を間接的に検証できます。

### 3. AWS Console での手動検証

AWS Console から Policy Engine の評価結果を確認できる可能性があります。

## 結論

Task #91 の主要な検証項目である「Cedar Policy のデプロイと Policy Engine での構文検証」は完了しました。さらに、Cognito ユーザーの作成、DynamoDB への登録、JWT トークンの取得も成功しました。

PartiallyAuthorizeActions API の実動作確認は、API サポート待ちのため **BLOCKED** 状態です。boto3/AWS CLI で API がサポートされ次第、検証を再開します。

現時点での検証結果は、第 8 章「Cedar Policy 検証」の技術的正確性を支持するものです。ただし、API の実動作確認が未完了であることを明記する警告メッセージは引き続き維持すべきです。

## 次のステップ

1. boto3/AWS CLI のアップデートを定期的に確認
2. AWS の公式ドキュメント・サンプルコードで PartiallyAuthorizeActions API の使用例を調査
3. AWS Support に API サポート状況を問い合わせ
4. 代替検証方法（CloudWatch Logs 確認など）の実施

## 参考情報

### 検証スクリプト

- `setup-cognito-users.py`: Cognito ユーザーと DynamoDB ポリシー情報の作成
- `test-partially-authorize.py`: PartiallyAuthorizeActions API の検証（API サポート待ち）

### 環境情報

- boto3 version: 1.42.54
- AWS CLI version: 2.x
- Region: us-east-1
- Python version: 3.11+

### 関連ドキュメント

- [AWS Bedrock AgentCore Gateway API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_Operations_Amazon_Bedrock_Agent_Core.html)
- [Cedar Policy Language](https://www.cedarpolicy.com/)
- [Cognito Pre Token Generation Lambda](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-token-generation.html)
