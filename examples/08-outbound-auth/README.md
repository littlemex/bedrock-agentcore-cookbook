# 08: Gateway Outbound Auth

AgentCore Gateway の Outbound Auth（外向き認証）機能の検証です。MCP サーバーが外部 API にアクセスする際に必要な認証情報を Gateway が管理・提供する仕組みです。

## 概要

Outbound Auth は、Gateway が MCP サーバーに代わって外部サービスへの認証情報を管理する機能です。以下の認証方式をサポートしています：

- **OAuth2 Credential Provider**: OAuth2 ベースの認証（25 ベンダー対応）
- **API Key Credential Provider**: API キーベースの認証
- **Gateway IAM Role**: AWS IAM ロールによる認証

## ファイル構成

```
08-outbound-auth/
├── README.md                           # このファイル
├── verify-outbound-auth.py             # 基本検証スクリプト
├── test-cognito-secret-rotation.py     # Cognito シークレット回転検証スクリプト
└── VERIFICATION_RESULT.md              # 検証結果レポート
```

## 検証内容

### 1. API の利用可否

OAuth2 Credential Provider API と API Key Credential Provider API の基本的な利用可否を確認します。

### 2. サポートされる OAuth2 ベンダー

`CreateOauth2CredentialProvider` API の `credentialProviderVendor` enum から、サポートされるベンダー一覧を取得します。

### 3. credentialProviderType の確認

`CreateGatewayTarget` API の `credentialProviderConfigurations` から、サポートされる認証プロバイダタイプを確認します。

### 4. OAuth2 Credential Provider の CRUD テスト

CustomOauth2 ベンダーを使用して、OAuth2 Credential Provider の作成・取得・削除を実行します。

### 5. API Key Credential Provider の CRUD テスト

API Key Credential Provider の作成・削除を実行します。

## サポートされる OAuth2 ベンダー

| # | ベンダー | 説明 |
|---|---------|------|
| 1 | GoogleOauth2 | Google OAuth2 |
| 2 | GithubOauth2 | GitHub OAuth2 |
| 3 | SlackOauth2 | Slack OAuth2 |
| 4 | SalesforceOauth2 | Salesforce OAuth2 |
| 5 | MicrosoftOauth2 | Microsoft OAuth2 |
| 6 | CustomOauth2 | カスタム OAuth2 (任意のプロバイダ) |
| 7 | AtlassianOauth2 | Atlassian (Jira, Confluence) |
| 8 | LinkedinOauth2 | LinkedIn OAuth2 |
| 9 | XOauth2 | X (旧 Twitter) OAuth2 |
| 10 | OktaOauth2 | Okta OAuth2 |
| 11 | OneLoginOauth2 | OneLogin OAuth2 |
| 12 | PingOneOauth2 | PingOne OAuth2 |
| 13 | FacebookOauth2 | Facebook OAuth2 |
| 14 | YandexOauth2 | Yandex OAuth2 |
| 15 | RedditOauth2 | Reddit OAuth2 |
| 16 | ZoomOauth2 | Zoom OAuth2 |
| 17 | TwitchOauth2 | Twitch OAuth2 |
| 18 | SpotifyOauth2 | Spotify OAuth2 |
| 19 | DropboxOauth2 | Dropbox OAuth2 |
| 20 | NotionOauth2 | Notion OAuth2 |
| 21 | HubspotOauth2 | HubSpot OAuth2 |
| 22 | CyberArkOauth2 | CyberArk OAuth2 |
| 23 | FusionAuthOauth2 | FusionAuth OAuth2 |
| 24 | Auth0Oauth2 | Auth0 OAuth2 |
| 25 | CognitoOauth2 | Amazon Cognito OAuth2 |

## credentialProviderType

Gateway Target に設定可能な認証プロバイダタイプ：

| タイプ | 説明 |
|-------|------|
| GATEWAY_IAM_ROLE | Gateway の IAM ロールを使用 |
| OAUTH | OAuth2 Credential Provider を使用 |
| API_KEY | API Key Credential Provider を使用 |

## Cognito Client Secret Lifecycle Management

### 概要

Amazon Cognito User Pool の App Client シークレットは、セキュリティのベストプラクティスとして定期的に回転（ローテーション）する必要があります。Cognito は以下の API を提供しています：

- **AddUserPoolClientSecret**: 新しいシークレットを追加（最大 2 つまで同時保持可能）
- **DeleteUserPoolClientSecret**: 旧シークレットを削除

これにより、**ゼロダウンタイムでのシークレット回転**が可能になります。

### シークレット回転の手順

#### Phase 1: 新しいシークレットの追加

```python
import boto3

cognito = boto3.client("cognito-idp", region_name="us-east-1")

# 新しいシークレットを追加
response = cognito.add_user_pool_client_secret(
    UserPoolId="us-east-1_XXXXXXXXX",
    ClientId="xxxxxxxxxxxxxxxxxxxxxxxxxx"
)

new_secret_id = response["ClientSecretId"]
print(f"New Secret ID: {new_secret_id}")
```

**重要**: 新しいシークレット値は、このレスポンスで一度だけ取得できます。必ず AWS Secrets Manager または環境変数に保存してください。

#### Phase 2: デュアルシークレット運用

新旧両方のシークレットが有効な状態で運用します。この期間中：
- 旧シークレットで発行された Token Vault 内のトークンは有効
- 新シークレットでの新規認証が可能
- **ダウンタイムなし**でアプリケーションを新シークレットに移行可能

#### Phase 3: OAuth2 Credential Provider の更新

```python
agentcore = boto3.client("bedrock-agentcore-control", region_name="us-east-1")

# Credential Provider を新しいシークレットで更新
agentcore.update_oauth2_credential_provider(
    credentialProviderId="provider-xxx",
    oauth2ProviderConfigInput={
        "cognitoOauth2ProviderConfig": {
            "clientSecret": new_secret_value  # 新しいシークレット値
        }
    }
)
```

#### Phase 4: 旧シークレットの削除

新シークレットでの動作確認後、旧シークレットを削除します。

```python
# 旧シークレットを削除
cognito.delete_user_pool_client_secret(
    UserPoolId="us-east-1_XXXXXXXXX",
    ClientId="xxxxxxxxxxxxxxxxxxxxxxxxxx",
    SecretId=old_secret_id  # DescribeUserPoolClient で取得
)
```

### 検証スクリプト

Cognito Client Secret の回転プロセスを検証するスクリプトを提供しています：

```bash
# 環境変数を設定
export USER_POOL_ID="us-east-1_XXXXXXXXX"
export CLIENT_ID="xxxxxxxxxxxxxxxxxxxxxxxxxx"
export AWS_DEFAULT_REGION="us-east-1"

# 検証スクリプトを実行
python3 test-cognito-secret-rotation.py
```

このスクリプトは以下を検証します：
1. CognitoOauth2 ベンダーでの Credential Provider 作成
2. AddUserPoolClientSecret による新しいシークレット追加
3. Credential Provider の clientSecret 更新
4. デュアルシークレット運用の動作確認
5. DeleteUserPoolClientSecret による旧シークレット削除
6. ゼロダウンタイムの確認

### ベストプラクティス

1. **定期的な回転**: 90 日ごとにシークレットを回転することを推奨
2. **Secrets Manager 連携**: シークレット値は AWS Secrets Manager に保存
3. **監視**: CloudWatch Logs で認証失敗をモニタリング
4. **テスト環境で検証**: 本番環境での回転前に、必ずテスト環境で手順を検証

### 注意事項

- Cognito App Client は最大 2 つのシークレットを同時に保持できます
- シークレット値は初回作成時のみ取得可能です
- DescribeUserPoolClient API ではシークレット値は取得できません（シークレット ID のみ）
- `SECRET_HASH` の計算には最新のシークレットを使用してください

## OAuth2 Credential Provider の作成例

```python
import boto3

client = boto3.client("bedrock-agentcore-control", region_name="us-east-1")

# CustomOauth2 の場合
response = client.create_oauth2_credential_provider(
    name="my-custom-oauth2-provider",
    credentialProviderVendor="CustomOauth2",
    oauth2ProviderConfigInput={
        "customOauth2ProviderConfig": {
            "clientId": "your-client-id",
            "clientSecret": "your-client-secret",
            "oauthDiscovery": {
                "authorizationServerMetadata": {
                    "issuer": "https://your-idp.example.com",
                    "authorizationEndpoint": "https://your-idp.example.com/oauth2/authorize",
                    "tokenEndpoint": "https://your-idp.example.com/oauth2/token",
                    "responseTypes": ["code"],
                }
            },
        }
    },
)
```

## API Key Credential Provider の作成例

```python
response = client.create_api_key_credential_provider(
    name="my-api-key-provider",
    apiKey="your-api-key-value",
)
```

## Gateway Target への設定

```python
client.create_gateway_target(
    gatewayIdentifier=gateway_id,
    name="my-target",
    targetType="MCP",
    endpoint={"url": "https://mcp-server.example.com"},
    credentialProviderConfigurations=[
        {
            "credentialProviderType": "OAUTH",
            "credentialProvider": {
                "oauth2CredentialProvider": {
                    "name": "my-custom-oauth2-provider"
                }
            },
        }
    ],
)
```

## 使い方

```bash
python3 verify-outbound-auth.py
```

## 参考資料

- AWS 公式サンプル: `02-use-cases/customer-support-assistant/scripts/cognito_credentials_provider.py`
- Zenn book: `books/agentcore-verification/06-outbound-auth.md`
