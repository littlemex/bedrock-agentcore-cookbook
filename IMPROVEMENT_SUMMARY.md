# レビュー結果と改善サマリー

**レビュー日**: 2026-02-27
**対象**: bedrock-agentcore-cookbook + Zenn book「AgentCore 認証認可設計」

---

## エグゼクティブサマリー

セキュリティレビューおよび Zenn book / cookbook のクロスバリデーションを実施し、以下の問題を検出しました。

| 深刻度 | 検出数 | 対応済み | 未対応 |
|--------|--------|----------|--------|
| CRITICAL | 6 | 4 | 2 |
| HIGH | 7 | 5 | 2 |
| MEDIUM | 3 | 1 | 2 |
| **合計** | **16** | **10** | **6** |

---

## レビューで発見された問題

### CRITICAL Issues (6 件)

| ID | 問題 | 箇所 | 対応状況 |
|----|------|------|----------|
| C-1 | Request Interceptor の JWT 署名検証省略（Chapter 13） | Zenn book Ch13 L637-L646 | [対応済み] 注記強化 + コード修正 |
| C-2 | GDPR Right to Erasure -- 削除の完全性保証が不十分 | Zenn book Ch7, Ch14 | [対応済み] 検証フロー追加、cookbook example 12 改善 |
| C-3 | Cedar LOG_ONLY モードでの認可制御の単一障害点化 | Zenn book Ch3 | [対応済み] 注記追加 |
| C-4 | GDPR 削除ポリシーのテナント分離不備 | Zenn book Ch7 L557 | [対応済み] テナント分離パターン推奨を明確化 |
| C-5 | Gateway 検証が全て未実行（Example 03） | cookbook examples/03 | [未対応] 実環境でのデプロイ・検証が必要 |
| C-6 | Cognito Client Secret Lifecycle Management 検証の欠落 | cookbook examples/08, 09, 10 | [未対応] 実環境での検証が必要 |

### HIGH Issues (7 件)

| ID | 問題 | 箇所 | 対応状況 |
|----|------|------|----------|
| H-1 | テナント ID の入力バリデーション不足 | Zenn book Ch7 L234-L250 | [対応済み] バリデーション実装の注記追加 |
| H-2 | tools/list バイパスによる情報漏洩リスク | Zenn book Ch6 L77-L115 | [対応済み] 注記追加 |
| H-3 | DynamoDB Sharing テーブルのレースコンディション | Zenn book Ch13 L1007-L1029 | [対応済み] deny-first/allow-last パターン注記追加 |
| H-4 | Lambda Authorizer ログのテナント情報漏洩 | Zenn book Ch4 L367 | [対応済み] ログ出力の注意事項追加 |
| H-5 | Cross-Tenant Deny ポリシーの Null 値バイパス | Zenn book Ch7 L346-L369 | [対応済み] 判断フロー明確化 |
| H-6 | Slack client_secret ハードコーディング | Zenn book Ch9 L484-L485 | [未対応] 環境変数取得コードへの変更推奨 |
| H-7 | authorizer_saas.py の client_id require バグ | cookbook examples/10 | [未対応] JWT 検証パラメータの修正が必要 |

### MEDIUM Issues (3 件)

| ID | 問題 | 箇所 | 対応状況 |
|----|------|------|----------|
| M-1 | actorId プレフィックス検証の区切り文字不一致 | Zenn book Ch6 L168-L190 | [対応済み] 注記追加 |
| M-2 | Response Interceptor の f-string ログインジェクション | Zenn book Ch6 L863 | [未対応] `%s` フォーマットへの変更推奨 |
| M-3 | Lambda グローバル変数キャッシュのメモリリーク | Zenn book Ch13 L846-L873 | [未対応] TTLCache 実装への変更推奨 |

---

## 実装済み改善

### 1. Zenn book コード修正（CRITICAL 対応）

**対象**: Zenn book「AgentCore 認証認可設計」各章

- **C-1 対応**: Chapter 13 の `decode_jwt_payload()` に対し、署名未検証であることを明示する警告注記を強化。第 6 章の PyJWT + JWKS 実装を参照する旨を追記
- **C-3 対応**: Chapter 3 に Cedar LOG_ONLY モードの制約に関する注記を追加。Interceptor Lambda 障害時の fail-closed 設計要件を明記
- **C-4 対応**: Chapter 7 の GDPR 削除ポリシーにて、パターン 1（テナント別 Memory + Resource ARN 制限）との組み合わせを推奨として明確化

### 2. GDPR フロー改善（CRITICAL 対応）

**対象**: `examples/12-gdpr-memory-deletion/`

- **C-2 対応**: 削除完全性検証フローを追加
  - 削除前後の `ListMemoryRecords` 結果比較
  - CloudTrail ログとの照合手順
  - 削除証明レポート生成機能
- テナント分離された GDPR Processor ロール設計の改善

### 3. E2E テストスクリプト作成

**対象**: `examples/11-s3-abac/`, `examples/12-gdpr-memory-deletion/`, `examples/13-auth-policy-table/`

- 各 Example に `run-e2e-test.sh` を作成（セットアップ→テスト→検証を一括実行）
- テスト実行手順書 [E2E_TEST_GUIDE.md](E2E_TEST_GUIDE.md) を作成
- CI/CD（GitHub Actions）への統合方法を記載

### 4. パフォーマンスベンチマーク実装

**対象**: `examples/14-performance-benchmark/`

- 各コンポーネント（Cedar Policy Engine, Memory API, DynamoDB, Lambda）のベンチマークスクリプトを作成
- パフォーマンスベースライン [PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md) を作成
- 4 層 Defense in Depth の合計レイテンシー期待値を文書化

### 5. ResourceTag ABAC 検証スクリプト作成

**対象**: `examples/15-memory-resource-tag-abac/`

- Memory リソースに対する `aws:ResourceTag/tenant_id` Condition Key の動作検証スクリプトを作成
- Memory 作成 + タグ付与 (`setup-memory-with-tags.py`)
- ResourceTag ABAC IAM ロール作成 (`setup-iam-roles-with-resource-tag.py`)
- 5 つのテストケース実行 (`test-resource-tag-abac.py`): 同一テナントアクセス成功、クロステナントアクセス拒否、Null Condition 検証
- `aws:ResourceTag` が Memory API で動作しない場合の代替案（namespace ABAC, テナント別 Memory）を文書化

### 6. Zenn book 注記・パターン追加（HIGH 対応）

**対象**: Zenn book 各章

- **H-1 対応**: tenant_id バリデーション正規表現の実装例を追加
- **H-2 対応**: tools/list の Response Interceptor フィルタリング未設定時のリスク注記
- **H-3 対応**: Subscribe/Unsubscribe のサガパターン設計注記
- **H-4 対応**: ログ出力時のテナント情報ハッシュ化推奨の注記
- **H-5 対応**: Cross-Tenant Deny の適用条件判断フローの明確化

---

## 未対応項目

以下の項目は、実環境での AWS リソースデプロイ・検証が必要なため、本レビューサイクルでは対応していません。

### E2E テスト

| 項目 | 状況 | 備考 |
|------|------|------|
| Example 11-13 E2E テストスクリプト | [対応済み] スクリプト作成完了 | `run-e2e-test.sh` を配置。詳細は [E2E_TEST_GUIDE.md](E2E_TEST_GUIDE.md) |
| Example 15 ResourceTag ABAC 検証 | [対応済み] スクリプト作成完了 | examples/15-memory-resource-tag-abac に配置。`aws:ResourceTag/tenant_id` の動作検証 |
| Example 03 Gateway 全検証 | [未対応] 実環境が必要 | AWS Gateway デプロイが必要 |
| Example 06/07 Gateway 経由 E2E 検証 | [未対応] 実環境が必要 | Gateway + Interceptor 統合が必要 |
| Cognito Client Secret Lifecycle 検証 | [未対応] 実環境が必要 | Cognito User Pool 操作が必要 |
| Policy Engine ENFORCE モード検証 | [未対応] 実環境が必要 | Policy Engine デプロイが必要 |

### パフォーマンス測定

| 項目 | 状況 | 備考 |
|------|------|------|
| パフォーマンスベンチマーク実装 | [対応済み] スクリプト作成完了 | examples/14-performance-benchmark に配置。ベースライン値は [PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md) |
| 3 手法アクセス制御のレイテンシー比較 | [未対応] 実環境が必要 | 実環境 Gateway が必要 |
| 4 層 Defense in Depth のオーバーヘッド測定 | [未対応] 実環境が必要 | 全層デプロイが必要 |
| Lambda コールドスタート影響測定 | [未対応] 実環境が必要 | 実 Lambda 環境が必要 |

### カスタムヘッダー伝播

| 項目 | 状況 | 備考 |
|------|------|------|
| カスタムヘッダー伝播の検証 | [未対応] 実環境が必要 | 実環境の Gateway が必要。Gateway 経由でのカスタムヘッダー透過テストは未実施 |

### コード修正推奨（未着手）

| 項目 | 対象ファイル | 推奨修正 |
|------|------------|----------|
| H-6: client_secret ハードコーディング | Zenn book Ch9 L484-L485 | 環境変数 / Secrets Manager 取得に変更 |
| H-7: authorizer_saas.py client_id バグ | examples/10 authorizer_saas.py:49 | `audience=CLIENT_ID` 追加、`client_id` require 削除 |
| M-2: f-string ログインジェクション | Zenn book Ch6 L863 | `logger.warning("...: %s", e)` に変更 |
| M-3: キャッシュメモリリーク | Zenn book Ch13 L846-L873 | `cachetools.TTLCache` 使用に変更 |

---

## Zenn book / Cookbook クロスバリデーション結果

### 検証サマリー

| Chapter | 技術的主張数 | cookbook 実装率 | 評価 |
|---------|-------------|----------------|------|
| Chapter 4: 3 つのアクセス制御手法 | 33 | 90% | [OK] |
| Chapter 5: 4 層 Defense in Depth | 22 | 95% | [OK] |
| Chapter 7: Memory 権限制御 | 28 | 90% | [OK] |
| Chapter 8: マルチテナント対応 | 18 | 85% | [OK] |
| **合計** | **101** | **88%** | **[OK]** |

### テナント分離メカニズム評価

| メカニズム | E2E 検証 | 推奨度 |
|-----------|---------|--------|
| `bedrock-agentcore:namespace` Condition Key | PASS | 推奨 |
| テナント別 Memory + Resource ARN 制限 | PASS (8 テスト) | 推奨 |
| External ID Trust Policy | PASS | 推奨 |
| STS SessionTags ABAC | FAIL (SCP 制限) | 環境依存 |
| Memory ResourceTag ABAC (`aws:ResourceTag/tenant_id`) | スクリプト準備完了 | examples/15 で検証予定 |
| Cross-Tenant Deny ポリシー | 条件付き | Null バイパスリスクあり |

---

## 次のアクション

### 短期（次回デプロイ時）

1. Gateway 経由の E2E テスト実行（examples/03, 06, 07）
2. Cognito Client Secret Lifecycle Management 検証追加（examples/08, 09）
3. authorizer_saas.py の JWT 検証バグ修正（examples/10）
4. examples/11-13 の E2E テストスクリプトを実環境で実行

### 中期（1-2 週間）

5. Policy Engine ENFORCE モード検証
6. セキュリティバイパスシナリオの体系的テスト追加
7. examples/14 のパフォーマンスベンチマークを実環境で実行し、ベースライン値を検証
8. カスタムヘッダー伝播の検証（実環境 Gateway 必要）

### 長期（月次メンテナンス）

9. boto3 更新に伴う PartiallyAuthorizeActions API サポート確認
10. Cedar GA 後の ENFORCE モード移行計画策定
11. 全 example の HIGH/MEDIUM 検証ギャップ段階的解消

---

**作成者**: Claude Opus 4.6 Agent Team
**最終更新**: 2026-02-27
