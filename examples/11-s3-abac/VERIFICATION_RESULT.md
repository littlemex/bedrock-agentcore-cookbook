# S3 ABAC E2E テスト結果

## 概要

| 項目 | 値 |
|------|-----|
| テスト名 | S3 ABAC E2E Test |
| 実行日時 | 2026-02-28T04:20:44Z |
| AWS アカウント | 776010787911 |
| 全体結果 | **FAIL** |

## ステップ別結果

```json
{
  "test_name": "s3-abac-e2e",
  "timestamp": "2026-02-28T04:20:44Z",
  "aws_account": "776010787911",
  "overall_status": "FAIL",
  "steps": [
    {"step": "setup-s3-buckets-dryrun", "status": "PASS", "detail": ""},{"step": "setup-s3-buckets", "status": "PASS", "detail": ""},{"step": "setup-iam-roles", "status": "PASS", "detail": ""},{"step": "test-s3-abac", "status": "FAIL", "detail": "PASS=0, FAIL=0"},{"step": "cleanup-s3-resources", "status": "PASS", "detail": ""}
  ]
}
```

## 検証内容

1. **S3 バケットセットアップ (dry-run)**: セットアップ内容の事前確認
2. **S3 バケット作成**: テナント別 S3 オブジェクトの作成とタグ付け
3. **IAM ロールセットアップ**: ABAC ポリシー付き IAM ロールの作成 (Tenant A/B)
4. **S3 ABAC テスト**: 4 テストケースの実行
   - Test 1: Tenant A が自身のオブジェクトにアクセス成功
   - Test 2: Tenant B が自身のオブジェクトにアクセス成功
   - Test 3: Tenant A が Tenant B のオブジェクトにアクセス拒否
   - Test 4: Tenant B が Tenant A のオブジェクトにアクセス拒否
5. **リソースクリーンアップ**: S3 バケット・IAM ロール・設定ファイルの削除
