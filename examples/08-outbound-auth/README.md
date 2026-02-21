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
├── README.md                    # このファイル
├── verify-outbound-auth.py      # 検証スクリプト
└── VERIFICATION_RESULT.md       # 検証結果レポート
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
