# bedrock-agentcore:actorId Condition Key の直接検証結果

**検証日時**: 2026-02-21 15:41 UTC
**検証者**: actorId Condition Key E2E 検証
**結果**: [BLOCKED] API が actorId コンテキストを提供していないため、Condition Key は実質的に未サポート

---

## 検証概要

`bedrock-agentcore:namespace` Condition Key が IAM レベルで正常に機能することが H-1 検証（2026-02-20）で確認された。同様のアプローチで `bedrock-agentcore:actorId` Condition Key も検証した。

## 検証環境

| 項目 | 値 |
|------|-----|
| AWS Account ID | 123456789012 |
| Region | us-east-1 |
| Memory ID | `e2e_phase5_memory_tenant_a-U3FzdrBpdk` |
| Strategy ID | `tenant_a_strategy-PlAJRCC34W` |
| Memory ARN | `arn:aws: bedrock-agentcore:us-east-1:123456789012: memory/e2e_phase5_memory_tenant_a-U3FzdrBpdk` |

## 検証方法

1. **テストロール A**: `bedrock-agentcore:actorId` Condition Key 付き IAM ポリシー（`StringEquals: {"bedrock-agentcore:actorId": "actor-alice"}`）
2. **テストロール B**: Condition Key なし IAM ポリシー（同一アクション、同一リソース）
3. **テスト内容**:
   - Test 1: ロール A で一致する actorId (`actor-alice`) の namespace に BatchCreateMemoryRecords
   - Test 2: ロール A で不一致の actorId (`actor-bob`) の namespace に BatchCreateMemoryRecords
   - Test 3: ロール B（Condition なし）で任意の actorId (`actor-bob`) に BatchCreateMemoryRecords
   - Test 4: ロール A で一致する actorId (`actor-alice`) に RetrieveMemoryRecords
   - Test 5: ロール A で不一致の actorId (`actor-bob`) に RetrieveMemoryRecords
   - Test 6: ロール A で ListActors

## IAM Policy（テストロール A）

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowMemoryAccessWithActorIdCondition",
    "Effect": "Allow",
    "Action": [
      "bedrock-agentcore:BatchCreateMemoryRecords",
      "bedrock-agentcore:RetrieveMemoryRecords",
      "bedrock-agentcore:ListMemoryRecords",
      "bedrock-agentcore:ListActors"
    ],
    "Resource": "arn:aws: bedrock-agentcore:us-east-1:123456789012: memory/e2e_phase5_memory_tenant_a-U3FzdrBpdk",
    "Condition": {
      "StringEquals": {
        "bedrock-agentcore:actorId": "actor-alice"
      }
    }
  }]
}
```

## 検証結果

| Test | Condition Key | actorId | API | 期待結果 | 実際の結果 | 判定 |
|------|--------------|---------|-----|---------|----------|------|
| 1 | 付き (`actor-alice`) | `actor-alice`（一致） | BatchCreateMemoryRecords | 成功 | **AccessDeniedException** | [NG] |
| 2 | 付き (`actor-alice`) | `actor-bob`（不一致） | BatchCreateMemoryRecords | AccessDeniedException | **AccessDeniedException** | [OK] (偶然) |
| 3 | なし | `actor-bob` | BatchCreateMemoryRecords | 成功 | **成功** | [OK] |
| 4 | 付き (`actor-alice`) | `actor-alice`（一致） | RetrieveMemoryRecords | 成功 | **AccessDeniedException** | [NG] |
| 5 | 付き (`actor-alice`) | `actor-bob`（不一致） | RetrieveMemoryRecords | AccessDeniedException | **AccessDeniedException** | [OK] (偶然) |
| 6 | 付き (`actor-alice`) | N/A | ListActors | 不明 | **AccessDeniedException** | [NG] |

### Test 1 のエラーメッセージ

```
An error occurred (AccessDeniedException) when calling the BatchCreateMemoryRecords operation:
User: arn:aws: sts::123456789012: assumed-role/e2e-actorid-test-role-with-condition/actorid-test-1
is not authorized to perform: bedrock-agentcore:BatchCreateMemoryRecords
on resource: arn:aws: bedrock-agentcore:us-east-1:123456789012: memory/e2e_phase5_memory_tenant_a-U3FzdrBpdk
because no identity-based policy allows the bedrock-agentcore:BatchCreateMemoryRecords action
```

## 分析

### Null Condition パターン

Test 1（一致）と Test 2（不一致）の両方で AccessDeniedException が発生している。一方、Test 3（Condition なし）では成功している。

これは **Null Condition パターン** と呼ばれる挙動で、以下のメカニズムで発生する:

1. IAM Policy に `bedrock-agentcore:actorId` Condition Key を設定
2. API 呼び出し時、API サービスが actorId のコンテキスト値を IAM に提供しない
3. IAM は Condition Key の値を **null** として評価
4. `StringEquals` 条件で null と `"actor-alice"` を比較 → 不一致
5. 結果: Condition が満たされず、**全てのリクエストが拒否される**

### namespace との比較

| 項目 | bedrock-agentcore:namespace | bedrock-agentcore:actorId |
|------|---------------------------|--------------------------|
| IAM Policy に設定可能か | はい | はい |
| Condition Key が IAM に認識されるか | はい | はい |
| API がコンテキスト値を提供するか | **はい** | **いいえ** |
| Condition による制御が機能するか | **機能する** | **機能しない** |
| 結果 | [PASS] | [BLOCKED] |

### なぜ namespace は機能して actorId は機能しないのか

- `namespace` は `BatchCreateMemoryRecords` と `RetrieveMemoryRecords` の API パラメータとして明示的に渡される。IAM はリクエストパラメータからコンテキスト値を抽出できる。
- `actorId` は現在の Memory API のパラメータに含まれていない。`actorId` は Memory サービス内部で管理される概念であり、API リクエストパラメータとして渡されない。そのため、IAM は actorId のコンテキスト値を取得できない。

## 結論

**[BLOCKED]** `bedrock-agentcore:actorId` Condition Key は現時点では**実質的に未サポート**である。

- IAM Policy の文法レベルでは受理される（Policy の作成・アタッチは成功する）
- しかし、Memory API が actorId コンテキストを IAM に提供しないため、Condition Key の値は常に null となる
- 結果として、actorId Condition Key を設定すると**全てのリクエストが拒否される**
- これは API サービス側の対応が必要であり、現時点ではアプリケーション側で回避できない

### 代替策

actorId ベースのアクセス制御を実現するには、以下の代替策が有効:

1. **namespace Condition Key を活用**: actorId を namespace パス内に埋め込む（例: `/tenant-a/actor-alice/`）ことで、namespace Condition Key で間接的に actorId ベースの制御が可能
2. **テナント別 Memory リソース**: テナント（またはアクター）ごとに別の Memory リソースを作成し、Resource ARN で制御
3. **アプリケーションレベル制御**: Lambda Authorizer や Gateway Interceptor で actorId を検証

## 検証スクリプト

`test-actorId-condition-key.py`

## テストロール（クリーンアップ済み）

- `e2e-actorid-test-role-with-condition`: actorId Condition Key 付き（削除済み）
- `e2e-actorid-test-role-without-condition`: Condition Key なし（削除済み）

---

**検証完了日**: 2026-02-21
**最終判定**: `bedrock-agentcore:actorId` Condition Key は **実質的に未サポート**（API がコンテキスト値を提供しない）
**推奨**: namespace Condition Key による間接的な actorId 制御を使用
