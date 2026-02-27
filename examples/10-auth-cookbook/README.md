# AgentCore Authentication & Authorization Cookbook

この cookbook は、AgentCore Gateway の認証認可実装の完全なサンプルコードを提供します。

## 修正完了サマリー

本 book の全 26 件の問題修正が完了しました：

### CRITICAL 修正（7 件）
- C-1: Chapter 13 Private Sharing 設計の全面修正（forbid 削除、Request Interceptor ベース）
- C-2: Memory API Action 名の修正（SearchMemory→RetrieveMemoryRecords）
- C-3: JWT claim 名の統一（custom:tenant_id→tenant_id）
- C-4: JWT 署名検証警告の追加
- C-5: E2E 検証状況の明確化
- C-6, C-7: リソース属性・制約の明確化

### HIGH 修正（7 件）
- H-3: IAM Action 名プレフィックス検証
- H-4: Cedar Action 名検証の警告
- H-5: structuredContent 検証追記
- H-6: 5 層→4 層 Defense in Depth の統一
- H-7: decode_jwt()関数定義のリファレンス追加

### MEDIUM/LOW 修正（12 件）
- M-1〜M-10: agent_id 属性、ヘッダー注入、キャッシュ戦略など
- L-1, L-2: Cedar 表記揺れの注記

## ディレクトリ構造

```
cookbook/
├── lambda-authorizer/          # Lambda Authorizer 実装
│   ├── authorizer_basic.py     # 基本実装（Chapter 4）
│   └── authorizer_saas.py      # SaaS マルチテナント実装（Chapter 12）
├── request-interceptor/        # Request Interceptor 実装
│   ├── interceptor_basic.py    # 基本実装（Chapter 6）
│   └── interceptor_private_sharing.py  # Private Sharing 実装（Chapter 13）
├── response-interceptor/       # Response Interceptor 実装
│   └── interceptor_basic.py    # 基本実装（Chapter 6）
├── pre-token-generation/       # Pre Token Generation Lambda
│   └── pre_token_gen_v2.py     # V2 形式（Chapter 10）
├── cognito-secret-management/  # Cognito Client Secret 管理（NEW）
│   └── cognito_secret_rotation.py  # ゼロダウンタイムローテーション（Chapter 8）
├── iam-policies/               # IAM ポリシーサンプル
│   └── memory_abac.json        # Memory ABAC（Chapter 7）
└── cedar-policies/             # Cedar ポリシーサンプル
    ├── basic_rbac.cedar        # 基本 RBAC（Chapter 5）
    ├── multi_tenant.cedar      # マルチテナント（Chapter 12）
    └── private_sharing.cedar   # Private Sharing（Chapter 13）
```

## 主要な実装

### 1. Lambda Authorizer

#### 基本実装（authorizer_basic.py）
- PyJWT + JWKS による署名検証
- テナント ID 検証
- fail-closed 設計

環境変数:
- `JWKS_URL`: Cognito JWKS URL
- `CLIENT_ID`: Cognito App Client ID

#### SaaS マルチテナント実装（authorizer_saas.py）
- 基本実装 + DynamoDB テナント情報取得
- テナントアクティブ状態の確認

追加環境変数:
- `TENANT_TABLE`: DynamoDB テナントテーブル名

### 2. Request Interceptor

#### 基本実装（interceptor_basic.py）
- MCP ライフサイクルメソッドのバイパス
- JWT 検証（Defense in Depth）
- ロールベースツール権限チェック

環境変数:
- `JWKS_URL`: Cognito JWKS URL（オプション、開発環境では base64 デコードのみ）
- `CLIENT_ID`: Cognito App Client ID（オプション）

#### Private Sharing 実装（interceptor_private_sharing.py）
- DynamoDB Sharing テーブル参照
- キャッシュ戦略（Lambda グローバル変数、TTL 60 秒）
- 共有先テナント検証

環境変数:
- `SHARING_TABLE`: DynamoDB Sharing テーブル名

### 3. Response Interceptor

#### 基本実装（interceptor_basic.py）
- ツールフィルタリング（RBAC）
- tools/list と Semantic Search の両レスポンス対応
- fail-closed 設計

環境変数:
- `JWKS_URL`: Cognito JWKS URL
- `CLIENT_ID`: Cognito App Client ID

### 4. Pre Token Generation Lambda

#### V2 形式実装（pre_token_gen_v2.py）
- DynamoDB からユーザー情報取得
- agent_id のサーバーサイド検証
- カスタムクレーム注入（role, groups, agent_id）

環境変数:
- `AUTH_POLICY_TABLE`: DynamoDB 認証ポリシーテーブル名

### 5. IAM ポリシー

#### Memory ABAC（memory_abac.json）
- bedrock-agentcore:namespace Condition Key でテナント分離
- Cross-Tenant Deny ポリシー

**重要**: このポリシーは修正済みの Action 名を使用しています：
- `bedrock-agentcore:RetrieveMemoryRecords`（旧: SearchMemory）
- `bedrock-agentcore:BatchCreateMemoryRecords`（旧: StoreMemory）
- `bedrock-agentcore:BatchDeleteMemoryRecords`

### 6. Cedar ポリシー

#### 基本 RBAC（basic_rbac.cedar）
- admin, user ロールの権限定義
- テナント + ロールの二重条件

#### マルチテナント（multi_tenant.cedar）
- テナント別 permit 定義
- クロステナント明示的 forbid

#### Private Sharing（private_sharing.cedar）
- 所有者 permit
- Public permit
- Private は deny-by-default（Request Interceptor で検証）

### 7. Cognito Client Secret Management（NEW）

#### ゼロダウンタイムローテーション（cognito_secret_rotation.py）

**概要**: 2026 年 2 月にリリースされた Cognito Client Secret Lifecycle Management 機能を使用して、ゼロダウンタイムでシークレットをローテーションします。

**主な機能**:
- デュアルシークレット運用（最大 2 つのシークレットを同時保持）
- AddUserPoolClientSecret API による新しいシークレットの追加
- DeleteUserPoolClientSecret API による古いシークレットの削除
- SECRET_HASH 計算と認証テスト

**ゼロダウンタイムローテーションフロー**:
1. 新しいシークレットを追加（AddUserPoolClientSecret）
2. アプリケーションを新しいシークレットに切り替え（両シークレットが同時有効）
3. 古いシークレットを削除（DeleteUserPoolClientSecret）

環境変数:
- `USER_POOL_ID`: Cognito User Pool ID
- `CLIENT_ID`: Cognito App Client ID
- `AWS_REGION`: AWS Region

**重要な制約**:
- 1 つの App Client に最大 2 つのシークレットまで同時保持可能
- 最低 1 つのシークレットは必須（全削除は不可）
- シークレット削除は不可逆的

**セキュリティベストプラクティス**:
- シークレット値は取得後すぐに安全な場所（AWS Secrets Manager など）に保存
- 定期的なローテーション（90 日推奨）
- ローテーション前に必ず新しいシークレットで認証テストを実施
- 古いシークレット削除前に、全アプリケーションが新しいシークレットに切り替わっていることを確認

## 使用方法

### 1. Lambda Authorizer のデプロイ

```bash
# 基本実装
cd lambda-authorizer
zip authorizer_basic.zip authorizer_basic.py
aws lambda update-function-code \
  --function-name your-authorizer-function \
  --zip-file fileb://authorizer_basic.zip
```

### 2. Interceptor のデプロイ

```bash
# Request Interceptor
cd request-interceptor
zip interceptor_basic.zip interceptor_basic.py
aws lambda update-function-code \
  --function-name your-request-interceptor \
  --zip-file fileb://interceptor_basic.zip

# Response Interceptor
cd ../response-interceptor
zip interceptor_basic.zip interceptor_basic.py
aws lambda update-function-code \
  --function-name your-response-interceptor \
  --zip-file fileb://interceptor_basic.zip
```

### 3. Lambda Layer の準備

PyJWT 使用時は、Lambda Layer としてパッケージが必要です：

```bash
mkdir -p python
pip install PyJWT cryptography -t python/
zip -r pyjwt-layer.zip python/
aws lambda publish-layer-version \
  --layer-name pyjwt-layer \
  --zip-file fileb://pyjwt-layer.zip \
  --compatible-runtimes python3.11
```

### 4. IAM ポリシーの適用

```bash
# IAM ポリシーの作成
aws iam create-policy \
  --policy-name MemoryABACPolicy \
  --policy-document file://iam-policies/memory_abac.json
```

### 5. Cedar ポリシーの登録

```bash
# AgentCore Policy Engine へのポリシー登録
aws bedrock-agent create-policy \
  --policy-store-id <your-policy-store-id> \
  --definition file://cedar-policies/basic_rbac.cedar
```

### 6. Cognito Client Secret のローテーション（NEW）

#### 環境変数の設定

```bash
export USER_POOL_ID=us-east-1_XXXXXXXXX
export CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
export AWS_REGION=us-east-1
```

#### 現在のシークレット一覧を確認

```bash
cd cognito-secret-management
python3 cognito_secret_rotation.py --list
```

出力例:
```
現在のシークレット数: 1
  [1] Secret ID: xxxxx-xxxxx-xxxxx
      Created: 2026-02-15 10:30:00
      Expires: N/A
```

#### 新しいシークレットを追加

```bash
python3 cognito_secret_rotation.py --add
```

出力例:
```
[SUCCESS] 新しいシークレットを追加しました
  Secret ID: yyyyy-yyyyy-yyyyy
  Secret Value: new-secret-value-xxxxxxxxxxxxxxxx

[IMPORTANT] 新しいシークレット値を安全に保存してください
この値は一度しか取得できません。

環境変数の設定例:
  export CLIENT_SECRET=new-secret-value-xxxxxxxxxxxxxxxx
```

#### 新しいシークレットで認証テスト

```bash
export TEST_USER_EMAIL=test@example.com
export TEST_USER_PASSWORD=YourPassword123!
export NEW_CLIENT_SECRET=new-secret-value-xxxxxxxxxxxxxxxx

python3 cognito_secret_rotation.py --test-auth \
  --test-username "$TEST_USER_EMAIL" \
  --test-password "$TEST_USER_PASSWORD" \
  --client-secret "$NEW_CLIENT_SECRET"
```

#### 古いシークレットを削除

```bash
# 削除する Secret ID を指定
python3 cognito_secret_rotation.py --delete xxxxx-xxxxx-xxxxx
```

#### ゼロダウンタイムローテーション（全自動）

すべてのステップを一括実行：

```bash
python3 cognito_secret_rotation.py --rotate \
  --test-username "$TEST_USER_EMAIL" \
  --test-password "$TEST_USER_PASSWORD" \
  --auto-confirm
```

このコマンドは以下を自動実行します：
1. 現在のシークレット一覧を確認
2. 新しいシークレットを追加
3. 新しいシークレットで認証テスト（テストユーザー指定時）
4. 古いシークレットを削除

**注意**: `--auto-confirm` を省略すると、削除前に確認プロンプトが表示されます。

#### CognitoOauth2 Credential Provider への適用

OutboundAuth（Chapter 8）で CognitoOauth2 Credential Provider を使用している場合、シークレットローテーション後に Credential Provider は自動的に新しいシークレットを使用します。

追加の設定は不要ですが、以下の点に注意してください：
- デュアルシークレット期間中、古いシークレットと新しいシークレットの両方で認証が可能
- TokenVault に保存されたトークンは、次回のリフレッシュ時に新しいシークレットで更新される
- 古いシークレット削除後、古いシークレットで取得されたトークンは次回リフレッシュ時にエラーになる（この場合、自動的に新しいシークレットで再認証される）

## 検証チェックリスト

### Phase 1: 基本動作確認
- [ ] Lambda Authorizer が正しく JWT 検証を実施
- [ ] 無効な JWT が拒否される
- [ ] 有効な JWT で isAuthorized: true が返却される

### Phase 2: Interceptor 動作確認
- [ ] Request Interceptor が MCP ライフサイクルメソッドをバイパス
- [ ] ロールベースのツール権限チェックが機能
- [ ] Response Interceptor がツールフィルタリングを実施

### Phase 3: テナント分離確認
- [ ] テナント A のユーザーがテナント B の Memory にアクセスできない
- [ ] IAM ABAC の Condition Key が正しく評価される
- [ ] Cedar forbid ポリシーがクロステナントアクセスを拒否

### Phase 4: Private Sharing 確認（Chapter 13）
- [ ] 所有者が自リソースにアクセス可能
- [ ] Public リソースに全テナントがアクセス可能
- [ ] Private 共有先テナントがアクセス可能
- [ ] 非共有テナントがアクセス拒否される
- [ ] DynamoDB キャッシュが機能（2 回目のアクセスがキャッシュヒット）

## トラブルシューティング

### JWT 検証エラー

**症状**: `Invalid token` エラー

**原因**:
- JWKS_URL が間違っている
- JWT の署名アルゴリズムが不一致
- JWT が期限切れ

**対処**:
```python
# JWKS URL の確認
JWKS_URL = "https://cognito-idp.{region}.amazonaws.com/{userPoolId}/.well-known/jwks.json"

# JWT デコードでクレーム確認
import jwt
token = "your-jwt-token"
unverified = jwt.decode(token, options={"verify_signature": False})
print(unverified)
```

### Memory API Action 名エラー

**症状**: IAM ポリシーで Access Denied が発生

**原因**: 旧 Action 名（SearchMemory, StoreMemory）を使用している

**対処**: 新 Action 名に修正
- `bedrock-agentcore:RetrieveMemoryRecords`
- `bedrock-agentcore:BatchCreateMemoryRecords`
- `bedrock-agentcore:BatchDeleteMemoryRecords`

### Private Sharing 動作不良

**症状**: 共有先テナントがアクセスできない

**原因**: forbid ポリシーが Request Interceptor より先に評価される

**対処**:
- forbid ポリシーを削除
- Request Interceptor で DynamoDB 検証を実施（interceptor_private_sharing.py）

### Cognito Client Secret Rotation エラー

#### エラー: LimitExceededException

**症状**: `シークレットの最大数（2 個）に達しています`

**原因**: 既に 2 つのシークレットが存在する状態で、新しいシークレットを追加しようとした

**対処**:
```bash
# 現在のシークレット一覧を確認
python3 cognito_secret_rotation.py --list

# 古いシークレットを削除してから追加
python3 cognito_secret_rotation.py --delete <old-secret-id>
python3 cognito_secret_rotation.py --add
```

#### エラー: InvalidParameterException（最後のシークレットは削除不可）

**症状**: `最後のシークレットは削除できません`

**原因**: 最後の 1 つのシークレットを削除しようとした

**対処**:
- 最低 1 つのシークレットは必須です
- 新しいシークレットを追加してから、古いシークレットを削除してください

```bash
# 正しい手順
python3 cognito_secret_rotation.py --add      # 新しいシークレット追加
python3 cognito_secret_rotation.py --delete <old-secret-id>  # 古いシークレット削除
```

#### エラー: NotAuthorizedException（SECRET_HASH 不一致）

**症状**: `Unable to verify secret hash for client`

**原因**: SECRET_HASH の計算が間違っている、または古いシークレットを使用している

**対処**:
```python
import base64
import hashlib
import hmac

def get_secret_hash(username: str, client_id: str, client_secret: str) -> str:
    """Cognito Secret Hash を計算"""
    message = bytes(username + client_id, "utf-8")
    secret = bytes(client_secret, "utf-8")
    dig = hmac.new(secret, msg=message, digestmod=hashlib.sha256).digest()
    return base64.b64encode(dig).decode()

# 使用例
secret_hash = get_secret_hash("user@example.com", CLIENT_ID, CLIENT_SECRET)
```

**重要**: SECRET_HASH は `username + client_id` の順で計算します（`client_id + username` ではありません）

#### デュアルシークレット期間中の認証エラー

**症状**: 新しいシークレットを追加したが、認証に失敗する

**原因**: アプリケーションがまだ古いシークレットを使用している

**対処**:
- デュアルシークレット期間中は、古いシークレットと新しいシークレットの両方で認証が可能
- アプリケーション側で新しいシークレットに切り替える
- 環境変数 `CLIENT_SECRET` を更新
- Lambda 関数の場合は、環境変数を更新して再デプロイ

```bash
# 環境変数を更新
export CLIENT_SECRET=<new-secret-value>

# Lambda 関数の場合
aws lambda update-function-configuration \
  --function-name your-function \
  --environment "Variables={CLIENT_SECRET=<new-secret-value>}"
```

## 参考リンク

- [AgentCore Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html)
- [Cedar Policy Language](https://www.cedarpolicy.com/)
- [PyJWT Documentation](https://pyjwt.readthedocs.io/)
- [AWS IAM ABAC](https://docs.aws.amazon.com/IAM/latest/UserGuide/introduction_attribute-based-access-control.html)
- [Amazon Cognito Developer Guide](https://docs.aws.amazon.com/cognito/latest/developerguide/)
- [Cognito User Pool Client Secrets](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html)
- [AWS Secrets Manager Best Practices](https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html)

## ライセンス

本 cookbook のコードは MIT ライセンスで提供されます。
