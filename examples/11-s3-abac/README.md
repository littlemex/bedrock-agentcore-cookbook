# Example 11: S3 ABAC (Attribute-Based Access Control)

この Example では、S3 オブジェクトタグと STS セッションタグを使用した ABAC パターンを実装します。

## 概要

マルチテナント環境において、S3 オブジェクトへのアクセス制御を実現する方法を示します。

- **オブジェクトタグ**: `s3:ExistingObjectTag/tenant_id`
- **セッションタグ**: `aws:PrincipalTag/tenant_id`
- **照合条件**: `StringEquals` で両タグが一致する場合のみアクセス許可

## アーキテクチャ

```
┌─────────────────┐
│  Tenant A User  │
│  (AssumeRole)   │
└────────┬────────┘
         │ SessionTags: tenant_id=tenant-a
         │
         v
┌─────────────────────────────────────────┐
│  IAM Policy with S3 ABAC Condition      │
│  Condition:                             │
│    StringEquals:                        │
│      s3:ExistingObjectTag/tenant_id:    │
│        ${aws:PrincipalTag/tenant_id}    │
└────────┬────────────────────────────────┘
         │
         v
┌─────────────────────────────────────────┐
│  S3 Bucket                              │
│  ├─ data/report.txt                     │
│  │  └─ Tags: tenant_id=tenant-a         │
│  └─ data/invoice.pdf                    │
│     └─ Tags: tenant_id=tenant-a         │
└─────────────────────────────────────────┘
```

## セットアップ手順

### 1. S3 バケット作成

```bash
python3 setup-s3-buckets.py
```

このスクリプトは以下を実行します:
- Tenant A/B 用の S3 バケット作成
- サンプルオブジェクトのアップロード
- オブジェクトタグの設定 (`tenant_id=tenant-a` など)

### 2. IAM ロール作成

```bash
python3 setup-iam-roles.py
```

このスクリプトは以下を実行します:
- Tenant A/B 用の IAM ロール作成
- Trust Policy 設定 (AssumeRole with External ID)
- S3 ABAC ポリシーのアタッチ

### 3. テスト実行

```bash
python3 test-s3-abac.py
```

以下のテストシナリオを実行します:

- **Test 1**: Tenant A が自身のオブジェクトにアクセス成功
- **Test 2**: Tenant B が自身のオブジェクトにアクセス成功
- **Test 3**: Tenant A が Tenant B のオブジェクトにアクセス拒否
- **Test 4**: Tenant B が Tenant A のオブジェクトにアクセス拒否

## クリーンアップ

```bash
python3 cleanup-s3-resources.py
```

このスクリプトは以下を削除します:
- S3 バケットとオブジェクト
- IAM ロールとポリシー

## IAM ポリシーの詳細

### S3 ABAC ポリシー

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowS3DownloadWithMatchingTag",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectTagging"],
      "Resource": "arn:aws:s3:::bucket-name/*",
      "Condition": {
        "StringEquals": {
          "s3:ExistingObjectTag/tenant_id": "${aws:PrincipalTag/tenant_id}"
        }
      }
    },
    {
      "Sid": "AllowS3UploadWithTag",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:PutObjectTagging"],
      "Resource": "arn:aws:s3:::bucket-name/*"
    },
    {
      "Sid": "AllowListBucket",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::bucket-name"
    }
  ]
}
```

### Trust Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::123456789012:root"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "tenant-a"
        }
      }
    }
  ]
}
```

## セキュリティのポイント

### 1. オブジェクトタグの一致

S3 ABAC では、オブジェクトに設定された `tenant_id` タグと、AssumeRole で付与された SessionTags の `tenant_id` が一致する場合のみアクセスを許可します。

### 2. アプリケーション層のバグでもブロック

仮にアプリケーション層で `tenant_id` の検証を誤っても、IAM レベルでクロステナントアクセスがブロックされます。

### 3. Defense in Depth

- **Layer 1**: アプリケーション層での tenant_id 検証
- **Layer 2**: IAM ポリシーでの S3 ABAC
- **Layer 3**: S3 Bucket Policy（オプション）

## 関連する Example

- **Example 02**: IAM ABAC (Memory Namespace)
- **Example 05**: End-to-End (STS SessionTags)

## 参考資料

- [AWS IAM: Using tags to control access to and for IAM users and roles](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_iam-tags.html)
- [Amazon S3: Controlling access to AWS resources using resource tags](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_tags.html)
- [AWS Security Blog: Simplify granting access to your AWS resources by using tags on AWS IAM users and roles](https://aws.amazon.com/blogs/security/simplify-granting-access-to-your-aws-resources-by-using-tags-on-aws-iam-users-and-roles/)
