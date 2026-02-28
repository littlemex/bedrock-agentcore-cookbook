# AuthPolicyTable E2E テスト結果

## 概要

| 項目 | 値 |
|------|-----|
| テスト名 | AuthPolicyTable E2E Test |
| 実行日時 | 2026-02-28T04:21:15Z |
| AWS アカウント | 776010787911 |
| リージョン | us-east-1 |
| テーブル名 | AuthPolicyTable |
| 全体結果 | **FAIL** |

## ステップ別結果

```json
{
  "test_name": "auth-policy-table-e2e",
  "timestamp": "2026-02-28T04:21:15Z",
  "aws_account": "776010787911",
  "region": "us-east-1",
  "overall_status": "FAIL",
  "steps": [
    {"step": "setup-dynamodb-table", "status": "PASS", "detail": ""},{"step": "seed-test-users-dryrun", "status": "PASS", "detail": ""},{"step": "seed-test-users", "status": "FAIL", "detail": "seed-test-users.py がエラーで終了"},{"step": "query-user-policy", "status": "FAIL", "detail": "一部のクエリが失敗"},{"step": "simulate-claims", "status": "FAIL", "detail": "一部のクレーム生成が失敗"}
  ]
}
```

## 検証内容

1. **DynamoDB テーブルセットアップ**: AuthPolicyTable の作成と GSI (TenantIdIndex) の確認
2. **テストデータ dry-run**: 投入前のデータ内容確認 (4 ユーザー)
3. **テストデータ投入**: --clear でリセット後、4 名のテストユーザーデータ投入
4. **Email/Tenant クエリ検証**:
   - Email クエリ (GetItem): 4 ユーザー
   - Tenant クエリ (GSI Query): 2 テナント
   - 全ユーザー一覧 (Scan)
5. **クレームシミュレーション**: Pre Token Generation Lambda と同等のクレーム生成テスト

## テストユーザー

| Email | Tenant | Role |
|-------|--------|------|
| admin@tenant-a.example.com | tenant-a | admin |
| user@tenant-a.example.com | tenant-a | user |
| admin@tenant-b.example.com | tenant-b | admin |
| readonly@tenant-b.example.com | tenant-b | readonly |
