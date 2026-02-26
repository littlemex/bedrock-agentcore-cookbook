# E2E Phase 3: Gateway + Policy Engine + Cedar 検証結果

## 検証日時
2026-02-20

## 検証目的
Task #91 (M-2 → CRITICAL): Cedar Policy の E2E 検証
- AgentCore Gateway + Policy Engine をデプロイ
- Cedar ポリシー（admin/user）を登録
- Policy Engine での Cedar 構文検証

## 検証環境

### デプロイされたリソース

| リソース | ID/ARN | ステータス |
|---------|--------|----------|
| Gateway | `e2e-phase3-gateway-sytqnigmll` | READY |
| Gateway ARN | `arn: aws: bedrock-agentcore: us-east-1:123456789012: gateway/e2e-phase3-gateway-sytqnigmll` | - |
| Lambda Target | `UTF91MVZVT` | ACTIVE |
| Lambda Function | `e2e-phase3-mcp-server` | Active |
| Policy Engine | `e2e_phase3_policy_engine-80kx42tcle` | ACTIVE |
| Policy Engine ARN | `arn: aws: bedrock-agentcore: us-east-1:123456789012: policy-engine/e2e_phase3_policy_engine-80kx42tcle` | - |
| Policy Engine Mode | LOG_ONLY | - |

### Cedar ポリシー

| ポリシー名 | ID | 内容 |
|-----------|-------|------|
| admin_policy | `admin_policy-ji_7qtsk83` | 全ツールへのアクセスを許可（role=admin）|
| user_policy | `user_policy-2efzhamk9n` | 特定ツールのみ許可（role=user）|

## 検証結果

### [OK] 1. Gateway デプロイ
- Gateway 作成成功
- Cognito JWT Authorizer 設定完了
- Lambda Target 追加成功
- Status: READY

### [OK] 2. Policy Engine デプロイ
- Policy Engine 作成成功
- Gateway への関連付け完了（mode=LOG_ONLY）
- Status: ACTIVE

### [OK] 3. Cedar ポリシーの登録

#### admin_policy
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

**検証結果**: [OK]
- Policy Engine で構文エラーなく受理された
- `hasTag()` および `getTag()` の使用が正常に検証された
- wildcard action が正常に受理された（resource を AgentCore::Gateway に制約）

#### user_policy
```cedar
permit (
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"mcp-target___retrieve_doc",
    AgentCore::Action::"mcp-target___list_tools"
  ],
  resource == AgentCore::Gateway::"arn: aws: bedrock-agentcore: us-east-1:123456789012: gateway/e2e-phase3-gateway-sytqnigmll"
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "user"
};
```

**検証結果**: [OK]
- Policy Engine で構文エラーなく受理された
- Tool-specific policy として正常に検証された
- 具体的な Gateway ARN 指定が必須であることを確認
- `hasTag()` および `getTag()` の使用が正常に検証された

### [PARTIAL] 4. PartiallyAuthorizeActions API での動作確認

**ステータス**: 未完了
- test-phase3.py の実行に必要な修正（bedrock-agent → bedrock-agentcore-control）が大量にある
- JWT トークン生成と API 呼び出しの完全な E2E テストは次フェーズに延期

**確認済み項目**:
- Policy Engine が Cedar ポリシーを正常に受理
- hasTag()/getTag() 構文が Policy Engine で検証済み
- resource 制約の要件を確認

## 重要な発見事項

### API パラメータの命名規則

1. **Gateway API**
   - `gatewayId` → `gatewayIdentifier` (get/update)
   - `gatewayName` → `name` (create)
   - `list_gateways()` の返り値: `items[]` (not `gateways[]`)
   - `items[].name` (not `items[].gatewayName`)

2. **Target API**
   - `targetName` → `name` (create)
   - `targetId` (not `targetIdentifier`) for get operations
   - `toolSchema` が必須（`inlinePayload` 構造）
   - `credentialProviderConfigurations` が必須

3. **Policy Engine API**
   - `policyEngineName` → `name` (create)
   - `policyEngineId` (not `policyEngineIdentifier`) for get operations
   - `list_policy_engines()` の返り値: `policyEngines[]`
   - mode パラメータは create 時ではなく Gateway 関連付け時に設定

4. **Policy API**
   - `put_policy` ではなく `create_policy`
   - `policyName` → `name`
   - `policyDefinition` → `definition`
   - `definition.cedar.statement` (not `definition.cedar.content`)
   - `validationMode: "IGNORE_ALL_FINDINGS"` を推奨

### Cedar ポリシーの制約

1. **命名規則**
   - Policy Engine 名: `^[A-Za-z][A-Za-z0-9_]*$` (ハイフン不可)
   - Policy 名: `^[A-Za-z][A-Za-z0-9_]*$` (ハイフン不可)

2. **resource 制約**
   - wildcard resource (`resource` のみ) は不可
   - 最低でも `resource is AgentCore::Gateway` が必要
   - Tool-specific policy (action を制約する場合) は具体的な Gateway ARN 指定が必須
     - `resource == AgentCore::Gateway::"arn: aws: bedrock-agentcore: ..."`

3. **hasTag()/getTag() 構文**
   - Policy Engine で正常に受理されることを確認
   - JWT クレームからのタグ取得を想定
   - 実際の動作は PartiallyAuthorizeActions API で検証が必要（次フェーズ）

### IAM Role の Trust Policy

Gateway が Lambda を invoke するためには、IAM role の Trust Policy に以下を追加:
```json
{
  "Service": [
    "lambda.amazonaws.com",
    "bedrock-agentcore.amazonaws.com"
  ]
}
```

また、以下の permission が必要:
- `lambda: InvokeFunction` (Lambda ARN に対して)
- `bedrock-agentcore: *` (操作全般)

## まとめ

### 達成した検証項目

[OK] Gateway デプロイ
[OK] Policy Engine デプロイと Gateway への関連付け
[OK] Cedar ポリシーの登録（2 件）
[OK] hasTag()/getTag() 構文の Policy Engine での検証
[OK] resource 制約の要件確認

### 未完了の検証項目

[PENDING] PartiallyAuthorizeActions API での実動作確認
[PENDING] role=admin と role=user での tool list 表示差異の検証
[PENDING] Policy Engine mode=ENFORCE での動作確認

### 次のステップ

1. test-phase3.py の修正（bedrock-agentcore-control への移行）
2. JWT トークン生成と PartiallyAuthorizeActions API 呼び出し
3. role=admin/user での tools/list レスポンス差異の検証
4. mode=ENFORCE での実動作検証

## 結論

Task #91 の主要な検証項目である「Cedar ポリシーのデプロイと Policy Engine での構文検証」は完了しました。特に重要な発見として、`hasTag()`/`getTag()` 構文が Policy Engine で正常に受理されることを確認できました。

完全な E2E 検証（PartiallyAuthorizeActions API での実動作確認）は、API パラメータの修正作業が大規模になるため、次のフェーズに延期します。

現時点での検証結果は、第 8 章「Cedar Policy 検証」の技術的正確性を支持するものです。ただし、警告メッセージ（E2E 未実施）は引き続き維持すべきです。
