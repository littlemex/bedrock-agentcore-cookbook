# AWS Bedrock AgentCore Policy Engine + Cedar Policies

このディレクトリには、AWS Bedrock AgentCore Policy Engine のデプロイと Cedar Policy の実装例が含まれています。

## 概要

Policy Engine は、Cedar Policy 言語を使用して、Gateway へのアクセスを細かく制御します。Role ベースのアクセス制御（RBAC）や属性ベースのアクセス制御（ABAC）を実装できます。

## ファイル構成

- `create-policy-engine.py` - Policy Engine の作成
- `associate-policy-engine.py` - Policy Engine を Gateway に関連付け
- `put-cedar-policies.py` - Cedar Policy の登録
- `update-policy-engine-mode.py` - Policy Engine モードの切り替え（LOG_ONLY/ENFORCE）（NEW）
- `test-enforce-mode.py` - ENFORCE モード E2E 検証スクリプト（NEW）
- `policies/admin-policy.cedar` - Admin ロール用ポリシー
- `policies/user-policy.cedar` - User ロール用ポリシー
- `E2E_PHASE3_VERIFICATION_RESULT.md` - E2E 検証結果レポート

## Cedar Policy の基本

Cedar は、AWS が開発したポリシー言語で、以下の要素で構成されます：

- **principal**: アクションを実行する主体（例: ユーザー、ロール）
- **action**: 実行されるアクション（例: ツール呼び出し）
- **resource**: アクセス対象のリソース（例: Gateway）
- **when**: 条件式（例: principal のタグ検証）

## 前提条件

- AWS CLI 設定済み（`aws configure`）
- AWS アカウントに以下の権限
  - `bedrock-agentcore:CreatePolicyEngine`
  - `bedrock-agentcore:GetPolicyEngine`
  - `bedrock-agentcore:CreatePolicy`
  - `bedrock-agentcore:UpdateGateway`
- Gateway がデプロイ済み（`03-gateway` を参照）

## セットアップ

1. 依存パッケージのインストール

```bash
pip install -r ../../requirements.txt
```

2. Policy Engine の作成

```bash
python create-policy-engine.py
```

Policy Engine 名は `^[A-Za-z][A-Za-z0-9_]*$` パターンに従う必要があります（ハイフン不可）。

3. Policy Engine を Gateway に関連付け

```bash
python associate-policy-engine.py
```

Gateway に Policy Engine を関連付ける際、以下のモードを選択できます：

- **LOG_ONLY**: ポリシー評価をログに記録するが、アクセスは許可する（デバッグ用）
- **ENFORCE**: ポリシー評価に基づいてアクセスを制御する

4. Cedar Policy の登録

```bash
python put-cedar-policies.py
```

`policies/` ディレクトリ内のすべての `.cedar` ファイルが Policy Engine に登録されます。

5. Cognito テストユーザーの作成

```bash
python setup-cognito-users.py
```

このスクリプトは、PartiallyAuthorizeActions API のテスト用に以下のユーザーを作成します：

- `admin-test-user` (role=admin)
- `user-test-user` (role=user)

**注意**: User Pool にカスタム属性 `custom: role` が定義されている必要があります。

6. PartiallyAuthorizeActions API のテスト

```bash
python test-partially-authorize.py
```

このスクリプトは、以下を検証します：

- role=admin ユーザーが全てのツールにアクセス可能であること
- role=user ユーザーが特定のツール（retrieve_doc, list_tools）のみアクセス可能であること
- Cedar Policy が期待通りに動作していること

7. Policy Engine モードの切り替え（NEW）

```bash
# 現在のモードを確認
python update-policy-engine-mode.py --get-mode

# LOG_ONLY モードに設定
python update-policy-engine-mode.py --mode LOG_ONLY

# ENFORCE モードに設定
python update-policy-engine-mode.py --mode ENFORCE
```

8. ENFORCE モード E2E 検証（NEW）

```bash
python test-enforce-mode.py
```

このスクリプトは、以下を検証します：

- LOG_ONLY モード: 全アクセスが許可される（ポリシー評価はログのみ）
- ENFORCE モードへの切り替え
- ENFORCE モード: Cedar Policy に基づいて実際にアクセス制御が行われる
  - role=admin: 全ツールへのアクセスが許可される
  - role=user: 制限されたツールのみアクセス可能
  - ポリシーにマッチしないリクエストは拒否される
- LOG_ONLY モードへの復元（クリーンアップ）

## Cedar Policy の例

### Admin ロール: 全ツールへのアクセス許可

`policies/admin-policy.cedar`:

```cedar
permit (
  principal is AgentCore::OAuthUser,
  action,
  resource is AgentCore::Gateway
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "admin"
};
```

このポリシーは以下を意味します：

- **principal is AgentCore::OAuthUser**: JWT トークンで認証されたユーザー
- **action**: すべてのアクション（ワイルドカード）
- **resource is AgentCore::Gateway**: Gateway リソース（最低限の制約）
- **when**: principal のタグに `role=admin` が含まれる場合

### User ロール: 特定ツールのみ許可

`policies/user-policy.cedar`:

```cedar
permit (
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"mcp-target___retrieve_doc",
    AgentCore::Action::"mcp-target___list_tools"
  ],
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1: ACCOUNT_ID: gateway/GATEWAY_ID"
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "user"
};
```

このポリシーは以下を意味します：

- **action in [...]**: 特定のツールのみ許可
- **resource == AgentCore::Gateway::"arn: ..."**: 具体的な Gateway ARN を指定（必須）
- **when**: principal のタグに `role=user` が含まれる場合

## 重要な制約と発見事項

### 1. Policy Engine 名の命名規則

Policy Engine 名は `^[A-Za-z][A-Za-z0-9_]*$` に従う必要があります：

- [OK] `my_policy_engine`
- [NG] `my-policy-engine`（ハイフン不可）

### 2. Policy 名の命名規則

Policy 名も同様に `^[A-Za-z][A-Za-z0-9_]*$` に従う必要があります：

- [OK] `admin_policy`
- [NG] `admin-policy`（ハイフン不可）

### 3. Cedar Policy の resource 制約

Cedar Policy では、resource にワイルドカード（`resource` のみ）を使用できません。最低でも以下のいずれかが必要です：

- **Admin ポリシー（全ツール許可）**: `resource is AgentCore::Gateway`
- **Tool-specific ポリシー**: `resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:..."`

### 4. hasTag() / getTag() 構文

JWT トークンのクレームから principal タグを取得するには、以下の構文を使用します：

```cedar
principal.hasTag("role") && principal.getTag("role") == "admin"
```

この構文は Policy Engine で正常に検証されます。

### 5. API パラメータの命名規則

**Policy Engine API: **

- **create_policy_engine**:
  - `name` (not `policyEngineName`)
  - mode パラメータは create 時ではなく、Gateway 関連付け時に設定

- **get_policy_engine**:
  - `policyEngineId` (not `policyEngineIdentifier`)

- **list_policy_engines**:
  - 返り値: `policyEngines[]`

**Policy API: **

- **create_policy** (not `put_policy`):
  - `name` (not `policyName`)
  - `definition` (not `policyDefinition`)
  - `definition.cedar.statement` (not `definition.cedar.content`)
  - `validationMode: "IGNORE_ALL_FINDINGS"` を推奨

## PartiallyAuthorizeActions API

Policy Engine を使用したアクセス制御を検証するには、`PartiallyAuthorizeActions` API を呼び出します：

```python
response = client.partially_authorize_actions(
    gatewayIdentifier="GATEWAY_ID",
    principalAccessToken="JWT_TOKEN",
    actionsToAuthorize=[
        {
            "actionId": "mcp-target___retrieve_doc",
            "actionDescription": "Retrieve document",
            "actionType": "CUSTOM"
        }
    ]
)
```

このレスポンスには、各アクションが許可されたか拒否されたかが含まれます。

## クリーンアップ

作成したリソースを削除するには：

```bash
# Policy の削除
# Policy Engine の削除
# Gateway からの関連付け解除
```

Policy Engine の削除前に、Gateway からの関連付けを解除する必要があります。

## 検証結果

E2E 検証の詳細は `E2E_PHASE3_VERIFICATION_RESULT.md` を参照してください。

### 検証済み項目

- [OK] Gateway デプロイ
- [OK] Policy Engine デプロイと Gateway への関連付け
- [OK] Cedar ポリシーの登録（2 件）
- [OK] hasTag()/getTag() 構文の Policy Engine での検証
- [OK] resource 制約の要件確認
- [OK] Policy Engine mode=ENFORCE での動作確認（NEW）
- [OK] LOG_ONLY → ENFORCE モード切り替えの検証（NEW）
- [OK] ENFORCE モードでのアクセス拒否の検証（NEW）

### 未検証項目

- [PENDING] PartiallyAuthorizeActions API での実動作確認
- [PENDING] role=admin と role=user での tool list 表示差異の検証

## 参考資料

- [Cedar Policy Language](https://www.cedarpolicy.com/)
- [AWS Bedrock AgentCore Policy Engine ドキュメント](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-policy.html)
- [AWS Bedrock AgentCore 公式サンプル - Policy Engine](https://github.com/aws-samples/amazon-bedrock-agentcore-samples)
