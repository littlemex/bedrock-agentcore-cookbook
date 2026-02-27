# H-1: bedrock-agentcore:namespace Condition Key の直接検証結果

**検証日時**: 2026-02-20
**検証者**: Task #88
**結果**: [PASS] Condition Key は IAM レベルで正常に機能

---

## 検証概要

Phase 4 レビューで「`bedrock-agentcore:namespace` Condition Key の未サポート根拠が間接的」と指摘されたため、直接検証を実施した。

## 検証方法

1. **テストロール 1**: namespace Condition Key 付き IAM ポリシー（`StringLike: {"bedrock-agentcore:namespace": "/tenant-a/*"}`）
2. **テストロール 2**: Condition Key なし IAM ポリシー
3. **テスト内容**:
   - テスト 1-1: ロール 1 で一致する namespace (`/tenant-a/user-001/`) にアクセス
   - テスト 1-2: ロール 1 で不一致の namespace (`/tenant-b/user-002/`) にアクセス
   - テスト 2: ロール 2 で任意の namespace (`/tenant-b/user-002/`) にアクセス

## 検証結果

| テスト | Condition Key | namespace | 期待結果 | 実際の結果 | 判定 |
|--------|--------------|-----------|---------|----------|------|
| 1-1 | 付き (`/tenant-a/*`) | `/tenant-a/user-001/` | 成功 | 成功 | [PASS] |
| 1-2 | 付き (`/tenant-a/*`) | `/tenant-b/user-002/` | **失敗** | **AccessDeniedException** | [PASS] |
| 2 | なし | `/tenant-b/user-002/` | 成功 | 成功 | [PASS] |

### テスト 1-2 のエラーメッセージ

```
An error occurred (AccessDeniedException) when calling the BatchCreateMemoryRecords operation:
User: arn:aws:sts::123456789012: assumed-role/e2e-h1-test-role-with-condition/h1-test-1-2
is not authorized to perform: bedrock-agentcore:BatchCreateMemoryRecords
on resource: arn:aws:bedrock-agentcore:us-east-1:123456789012: memory/e2e_phase5_memory_tenant_a-U3FzdrBpdk
because no identity-based policy allows the bedrock-agentcore:BatchCreateMemoryRecords action
```

## 結論

**[CRITICAL]** `bedrock-agentcore:namespace` Condition Key は **IAM レベルで正常に評価されている**。

- Condition Key を設定すると、不一致の namespace でのアクセスは **IAM によって拒否される**
- これは、書籍で記載されているように Condition Key が「未サポート」ではなく、**サポートされている**ことを意味する

## Phase 4 / E2E Phase 5 との矛盾

### E2E Phase 5 の結論

E2E Phase 5（2026-02-20 実施）では以下のように結論づけられていた：

> **E2E Phase 5 で判明した CRITICAL な制約（2026-02-20）**:
> 2. **`bedrock-agentcore:namespace` Condition Key は未サポート**: IAM ポリシーの Condition として機能しない

### 本検証による訂正

**E2E Phase 5 の結論は誤り**であった。`bedrock-agentcore:namespace` Condition Key は IAM レベルで正常に機能する。

E2E Phase 5 で Condition Key を使わない代替方式（テナント別 Memory + Resource ARN）を採用した理由は、STS SessionTags が組織 SCP で制限されていたためだが、Condition Key 自体は機能していた。

## 書籍への影響

### 修正が必要な箇所

1. **07-iam-abac.md**:
   - 行 22-23 の alert box: 「bedrock-agentcore:namespace Condition Key は未サポート」を削除
   - Condition Key テーブル（行 98-107）: namespace を FAIL から **PASS** に変更
   - E2E Phase 5 検証結果セクション: Condition Key が機能することを追記

2. **usecase-04-saas-multitenant.md**:
   - セクション 6 の alert box: namespace Condition Key の注記を削除
   - 代替方式セクション: Condition Key が機能することを追記

3. **09-conclusion.md**:
   - セクション 9.1 の alert box（行 20-26）: 「bedrock-agentcore:namespace Condition Key は未サポート」を削除
   - Phase 5 結果の更新

4. **agentcore-constraints-report.md**:
   - TOP10 の項目 10 を削除または訂正

### 追加すべき情報

- H-1 検証により、namespace Condition Key が機能することを E2E で実証
- STS SessionTags ABAC + namespace Condition Key の組み合わせが有効（SCP が許可する環境下）
- テナント別 Memory リソース方式は SCP 制限がある環境での代替策であり、必須ではない

## 検証スクリプト

`/home/coder/data-science/claudecode/tests/e2e-phase5-memory/test-h1-condition-key.py`

## IAM ロール

- `e2e-h1-test-role-with-condition`: namespace Condition Key 付き
- `e2e-h1-test-role-without-condition`: Condition Key なし

---

**検証完了日**: 2026-02-20
**最終判定**: bedrock-agentcore:namespace Condition Key は **サポートされている**
**Phase 4 指摘への回答**: HR-3 の「間接的な根拠」を「直接検証による確認」に昇格
