# AWS Bedrock AgentCore Gateway Deployment

このディレクトリには、AWS Bedrock AgentCore Gateway のデプロイ手順とサンプルコードが含まれています。

## 概要

AgentCore Gateway は、MCP（Model Context Protocol）サーバーやカスタムツールを Bedrock エージェントに統合するためのエントリポイントです。Gateway を使用すると、Lambda 関数、HTTP エンドポイント、または MCP サーバーをターゲットとして追加できます。

## ファイル構成

- `deploy-gateway.py` - Gateway のデプロイスクリプト
- `create-policy-engine.py` - Policy Engine の作成
- `put-cedar-policies.py` - Cedar ポリシーの登録
- `test-phase3.py` - E2E 検証スクリプト
- `cleanup.py` - 作成したリソースのクリーンアップ
- `VERIFICATION_RESULT.md` - 検証結果レポート

## 前提条件

- AWS CLI 設定済み（`aws configure`）
- AWS アカウントに以下の権限
  - `bedrock-agentcore: CreateGateway`
  - `bedrock-agentcore: GetGateway`
  - `bedrock-agentcore: DeleteGateway`
  - `bedrock-agentcore: CreateGatewayTarget`
  - `iam: CreateRole`
  - `iam: PassRole`
  - `lambda: InvokeFunction`

- Cognito User Pool（JWT Authorizer を使用する場合）
- Lambda 関数（MCP サーバーまたはカスタムツール）

## Gateway の構成要素

### 1. Gateway

Gateway は以下の要素で構成されます：

- **Protocol Type**: `MCP` または `HTTP`
- **Authorizer Type**: `CUSTOM_JWT` または `NONE`
- **Role ARN**: Gateway が他のサービスを呼び出すための IAM Role

### 2. Gateway Target

Gateway Target は、実際のツールやサービスを表します：

- **Lambda Target**: Lambda 関数を呼び出す
- **HTTP Target**: HTTP エンドポイントを呼び出す
- **MCP Target**: MCP サーバーを呼び出す

## セットアップ

1. 依存パッケージのインストール

```bash
pip install -r ../../requirements.txt
```

2. Gateway のデプロイ

```bash
python deploy-gateway.py
```

このスクリプトは以下を実行します：
- IAM Role の作成（Trust Policy に `bedrock-agentcore.amazonaws.com` を追加）
- Gateway の作成
- Gateway Target（Lambda）の追加
- Cognito JWT Authorizer の設定

実行が成功すると、`gateway-config.json` が作成されます。

3. Policy Engine の作成

```bash
# Gateway ID を環境変数に設定
export GATEWAY_ID=$(python3 deploy-gateway.py --get-id)

# LOG_ONLY モードで Policy Engine を作成
python3 create-policy-engine.py --mode LOG_ONLY

# Policy Engine ID を環境変数に設定
export POLICY_ENGINE_ID=$(python3 create-policy-engine.py --get-id)
```

4. Cedar ポリシーの登録

```bash
# 全てのポリシーを登録（admin, user, guest）
python3 put-cedar-policies.py

# 特定のポリシーのみ登録
python3 put-cedar-policies.py --policy admin

# 既存のポリシーを確認
python3 put-cedar-policies.py --list
```

5. E2E 検証の実行

```bash
# 検証スクリプトを実行
python3 test-phase3.py
```

検証項目：
- Test 1: JWT 認証バイパステスト（無効 JWT、JWT なしでの拒否）
- Test 2: Policy Engine LOG_ONLY モードの動作確認
- Test 3: Policy Engine ENFORCE モードの動作確認
- Test 4: Cedar Policy による RBAC（Admin ロール）
- Test 5: Cedar Policy による RBAC（User ロール）
- Test 6: Gateway IAM Role の権限昇格防止

## Policy Engine と Cedar Policy

### Policy Engine のモード

- **LOG_ONLY**: ポリシー評価をログに記録するが、アクセス制御は行わない
- **ENFORCE**: Cedar ポリシーに基づいて実際にアクセス制御を行う

### モードの変更

```bash
# ENFORCE モードに変更
python3 create-policy-engine.py --update-mode ENFORCE

# LOG_ONLY モードに戻す
python3 create-policy-engine.py --update-mode LOG_ONLY
```

### Cedar ポリシーの例

#### Admin Policy
```cedar
// Admin ロールは全てのツールにアクセス可能
permit (
    principal is AgentCore::OAuthUser,
    action,
    resource
)
when {
    principal.hasTag("role") &&
    principal.getTag("role") == "admin"
};
```

#### User Policy
```cedar
// User ロールは制限されたツールのみアクセス可能
permit (
    principal is AgentCore::OAuthUser,
    action in [
        AgentCore::Action::"mcp-target___retrieve_doc",
        AgentCore::Action::"mcp-target___list_tools"
    ],
    resource
)
when {
    principal.hasTag("role") &&
    principal.getTag("role") == "user"
};
```

#### Guest Policy (forbid)
```cedar
// Guest ロールは全てのツールへのアクセスを拒否
forbid (
    principal is AgentCore::OAuthUser,
    action,
    resource
)
when {
    principal.hasTag("role") &&
    principal.getTag("role") == "guest"
};
```

## 重要な API パラメータ

### Gateway API

boto3 クライアント: `bedrock-agentcore-control`

- **create_gateway**:
  - `name` (not `gatewayName`)
  - `authorizerConfiguration` (not `authorizationConfiguration`)
  - `customJWTAuthorizer` 内に `issuer`, `audiences`, `clientIds` を指定

- **get_gateway**:
  - `gatewayIdentifier` (not `gatewayId`)

- **list_gateways**:
  - 返り値: `items[]` (not `gateways[]`)
  - フィールド名: `items[].name` (not `items[].gatewayName`)

### Target API

- **create_gateway_target**:
  - `name` (not `targetName`)
  - `toolSchema` が必須（`inlinePayload` 構造）
  - `credentialProviderConfigurations` が必須

- **get_gateway_target**:
  - `targetId` (not `targetIdentifier`)

## IAM Role の設定

Gateway が Lambda を呼び出すためには、IAM Role の Trust Policy に以下を追加する必要があります：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": [
          "lambda.amazonaws.com",
          "bedrock-agentcore.amazonaws.com"
        ]
      },
      "Action": "sts: AssumeRole"
    }
  ]
}
```

また、以下の権限が必要です：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "lambda: InvokeFunction",
      "Resource": "arn: aws: lambda: REGION: ACCOUNT: function/FUNCTION_NAME"
    },
    {
      "Effect": "Allow",
      "Action": "bedrock-agentcore: *",
      "Resource": "*"
    }
  ]
}
```

## クリーンアップ

作成したリソースを削除するには：

```bash
python cleanup.py
```

## トラブルシューティング

### Error: Gateway service is not authorized to perform AssumeRole

**原因**: IAM Role の Trust Policy に `bedrock-agentcore.amazonaws.com` が含まれていない

**解決策**: Trust Policy に `bedrock-agentcore.amazonaws.com` を追加してください

### Error: Unknown parameter 'gatewayId'

**原因**: API パラメータ名が間違っている

**解決策**: `gatewayId` → `gatewayIdentifier` に変更してください

## 参考資料

- [AWS Bedrock AgentCore Gateway API ドキュメント](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_Operations_Amazon_Bedrock_Agent_Core.html)
- [AWS Bedrock AgentCore 公式サンプル - Gateway](https://github.com/aws-samples/amazon-bedrock-agentcore-samples/tree/main/02-use-cases/device-management-agent/gateway)
