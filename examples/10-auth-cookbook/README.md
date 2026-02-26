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

## 参考リンク

- [AgentCore Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html)
- [Cedar Policy Language](https://www.cedarpolicy.com/)
- [PyJWT Documentation](https://pyjwt.readthedocs.io/)
- [AWS IAM ABAC](https://docs.aws.amazon.com/IAM/latest/UserGuide/introduction_attribute-based-access-control.html)

## ライセンス

本 cookbook のコードは MIT ライセンスで提供されます。
