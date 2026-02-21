# Outbound Auth 検証結果

検証日: 2026-02-21
検証者: Claude Opus 4.6
リージョン: us-east-1

---

## 検証サマリー

| 項目 | 結果 |
|------|------|
| API 利用可否 | 2 PASS / 0 FAIL |
| サポートベンダー取得 | PASS (25 ベンダー) |
| credentialProviderType 取得 | PASS (3 タイプ) |
| OAuth2 Provider CRUD | 3 PASS / 0 FAIL |
| API Key Provider CRUD | 2 PASS / 0 FAIL |
| **総合判定** | **9 PASS / 0 FAIL** |

---

## 1. API 利用可否

| API | 結果 |
|-----|------|
| list_oauth2_credential_providers | PASS (0 providers) |
| list_api_key_credential_providers | PASS (0 providers) |

---

## 2. サポートされる OAuth2 ベンダー (25 種)

| # | ベンダー |
|---|---------|
| 1 | GoogleOauth2 |
| 2 | GithubOauth2 |
| 3 | SlackOauth2 |
| 4 | SalesforceOauth2 |
| 5 | MicrosoftOauth2 |
| 6 | CustomOauth2 |
| 7 | AtlassianOauth2 |
| 8 | LinkedinOauth2 |
| 9 | XOauth2 |
| 10 | OktaOauth2 |
| 11 | OneLoginOauth2 |
| 12 | PingOneOauth2 |
| 13 | FacebookOauth2 |
| 14 | YandexOauth2 |
| 15 | RedditOauth2 |
| 16 | ZoomOauth2 |
| 17 | TwitchOauth2 |
| 18 | SpotifyOauth2 |
| 19 | DropboxOauth2 |
| 20 | NotionOauth2 |
| 21 | HubspotOauth2 |
| 22 | CyberArkOauth2 |
| 23 | FusionAuthOauth2 |
| 24 | Auth0Oauth2 |
| 25 | CognitoOauth2 |

---

## 3. credentialProviderType

| タイプ | 説明 |
|-------|------|
| GATEWAY_IAM_ROLE | Gateway の IAM ロールで認証 |
| OAUTH | OAuth2 Credential Provider |
| API_KEY | API Key Credential Provider |

---

## 4. OAuth2 Credential Provider CRUD テスト

| 操作 | 結果 | 備考 |
|------|------|------|
| 作成 (create) | PASS | CustomOauth2 ベンダーで作成 |
| 取得 (get) | PASS | Vendor: CustomOauth2 |
| 削除 (delete) | PASS | 正常削除 |

### 作成された ARN

```
arn: aws: bedrock-agentcore: us-east-1:776010787911: token-vault/default/oauth2credentialprovider/e2e-test-outbound-auth-provider
```

### ARN 構造の分析

```
arn: aws: bedrock-agentcore: {region}: {account}: token-vault/default/oauth2credentialprovider/{name}
```

- サービス: `bedrock-agentcore`
- リソースタイプ: `token-vault/default/oauth2credentialprovider`
- Token Vault (`default`) が認証情報を安全に格納

---

## 5. API Key Credential Provider CRUD テスト

| 操作 | 結果 | 備考 |
|------|------|------|
| 作成 (create) | PASS | テスト用 API キーで作成 |
| 削除 (delete) | PASS | 正常削除 |

### 作成された ARN

```
arn: aws: bedrock-agentcore: us-east-1:776010787911: token-vault/default/apikeycredentialprovider/e2e-test-api-key-provider
```

### ARN 構造の分析

```
arn: aws: bedrock-agentcore: {region}: {account}: token-vault/default/apikeycredentialprovider/{name}
```

---

## 6. 重要な発見事項

### 6.1 Token Vault による認証情報管理

Outbound Auth の認証情報は `token-vault/default` というリソース配下に格納される。これは AWS Secrets Manager のような専用の安全なストレージであり、クライアントシークレットや API キーが平文で Gateway 設定に含まれることを防ぐ。

### 6.2 25 種の OAuth2 ベンダー対応

主要な SaaS プロバイダ（Google, GitHub, Slack, Salesforce, Microsoft 等）がネイティブでサポートされており、各ベンダー固有の OAuth2 フローに対応。`CustomOauth2` を使えば任意の OAuth2 プロバイダにも対応可能。

### 6.3 3 種の認証プロバイダタイプ

Gateway Target の `credentialProviderConfigurations` では以下の 3 タイプが利用可能:
- `GATEWAY_IAM_ROLE`: AWS サービス連携に最適
- `OAUTH`: 外部 SaaS API 連携に最適
- `API_KEY`: シンプルな API キー認証に最適

### 6.4 CognitoOauth2 ベンダーの存在

Amazon Cognito が OAuth2 ベンダーの一つとしてサポートされている。これにより、Gateway の認証 (Custom JWT with Cognito) と Outbound Auth (CognitoOauth2) の両方で Cognito を活用できる統一的なアーキテクチャが可能。

---

## 7. 検証で使用した API 操作

| API | 操作 |
|-----|------|
| list_oauth2_credential_providers | OAuth2 プロバイダ一覧取得 |
| create_oauth2_credential_provider | OAuth2 プロバイダ作成 |
| get_oauth2_credential_provider | OAuth2 プロバイダ取得 |
| delete_oauth2_credential_provider | OAuth2 プロバイダ削除 |
| list_api_key_credential_providers | API Key プロバイダ一覧取得 |
| create_api_key_credential_provider | API Key プロバイダ作成 |
| delete_api_key_credential_provider | API Key プロバイダ削除 |

---

検証完了日: 2026-02-21
