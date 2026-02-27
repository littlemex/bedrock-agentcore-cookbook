# Example 15: Memory ResourceTag ABAC (aws:ResourceTag/tenant_id)

> **[注意] E2E テスト未実施**: この Example は Zenn book の技術的主張を検証するためのリファレンス実装です。コードのローカル構文検証は完了していますが、実際の AWS 環境での E2E テストは未実施です。本番利用前に必ず実環境での検証を行ってください。

この Example では、Memory API に対する `aws:ResourceTag/tenant_id` Condition Key の動作を検証します。

## 概要

マルチテナント環境において、Memory リソースへのアクセス制御を `aws:ResourceTag` で実現するパターンを検証します。

- **リソースタグ**: Memory リソースに `tenant_id` タグを付与
- **セッションタグ**: `aws:PrincipalTag/tenant_id`（STS SessionTags で付与）
- **照合条件**: `StringEquals` で両タグが一致する場合のみアクセス許可

## アーキテクチャ

```
                                          Memory A
                                          (tag: tenant_id=tenant-a)
                                          +-------------------+
+-------------------+                     |                   |
| Tenant A User     |  SessionTags:       |  Records for      |
| (AssumeRole)      | ---- tenant_id  --> |  Tenant A         |
+-------------------+     =tenant-a       |                   |
                                          +-------------------+
         |
         |  IAM Policy:
         |  aws:ResourceTag/tenant_id
         |    == ${aws:PrincipalTag/tenant_id}
         |
         |                                Memory B
         |                                (tag: tenant_id=tenant-b)
         |                                +-------------------+
         +-------- DENIED --------------> |                   |
                                          |  Records for      |
                                          |  Tenant B         |
                                          |                   |
                                          +-------------------+
```

## S3 ABAC (Example 11) との比較

| 項目 | S3 ABAC (Example 11) | Memory ResourceTag ABAC (Example 15) |
|------|---------------------|--------------------------------------|
| Condition Key | `s3:ExistingObjectTag/tenant_id` | `aws:ResourceTag/tenant_id` |
| タグ対象 | S3 オブジェクト | Memory リソース |
| タグ付与方法 | `PutObjectTagging` | `TagResource` |
| 粒度 | オブジェクトレベル | リソース（Memory）レベル |
| 検証ステータス | リファレンス実装 | 動作確認中 |

## namespace ABAC (Example 02) との比較

| 項目 | namespace ABAC (Example 02) | ResourceTag ABAC (Example 15) |
|------|----------------------------|-------------------------------|
| Condition Key | `bedrock-agentcore:namespace` | `aws:ResourceTag/tenant_id` |
| 制御粒度 | namespace パスレベル | Memory リソースレベル |
| 動的変数 | `${aws:PrincipalTag/tenant_id}` | `${aws:PrincipalTag/tenant_id}` |
| 検証ステータス | [OK] 動作確認済み | 動作確認中 |
| 用途 | Record レベルの分離 | Memory リソースレベルの分離 |

## ファイル構成

| ファイル | 説明 |
|---------|------|
| `setup-memory-with-tags.py` | Memory 作成 + tenant_id タグ付与 |
| `setup-iam-roles-with-resource-tag.py` | ResourceTag ABAC IAM ロール作成 |
| `test-resource-tag-abac.py` | 5 つのテストケースを実行 |
| `cleanup-resources.py` | リソースのクリーンアップ |
| `phase15-config.json.example` | 設定ファイルのテンプレート |
| `VERIFICATION_RESULT.md.template` | 検証結果テンプレート |

## セットアップ手順

### 1. Memory 作成とタグ付与

```bash
python3 setup-memory-with-tags.py
```

このスクリプトは以下を実行します:
- Tenant A 用 Memory 作成（タグ: `tenant_id=tenant-a`）
- Tenant B 用 Memory 作成（タグ: `tenant_id=tenant-b`）
- `TagResource` API でタグを付与
- `ListTagsForResource` でタグを確認

### 2. IAM ロール作成

```bash
python3 setup-iam-roles-with-resource-tag.py
```

このスクリプトは以下を実行します:
- Tenant A/B 用の IAM ロール作成
- Trust Policy 設定 (`sts:AssumeRole` + `sts:TagSession`)
- ResourceTag ABAC ポリシーのアタッチ

### 3. テスト実行

```bash
# IAM ポリシー伝播待機（推奨）
sleep 10

python3 test-resource-tag-abac.py
```

以下のテストシナリオを実行します:

- **Test 1**: Tenant A が自身の Memory にアクセス成功
- **Test 2**: Tenant B が自身の Memory にアクセス成功
- **Test 3**: Tenant A が Tenant B の Memory にアクセス拒否（ResourceTag 不一致）
- **Test 4**: Tenant B が Tenant A の Memory にアクセス拒否（ResourceTag 不一致）
- **Test 5**: ResourceTag なしの Memory へのアクセス拒否（Null Condition 検証）

テスト結果は `VERIFICATION_RESULT.md` に自動出力されます。

## クリーンアップ

```bash
python3 cleanup-resources.py
```

このスクリプトは以下を削除します:
- Memory リソース（Tenant A, Tenant B）
- IAM ロールとインラインポリシー
- 設定ファイル

## IAM ポリシーの詳細

### Memory ResourceTag ABAC ポリシー

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowMemoryOperationsWithMatchingTag",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:BatchCreateMemoryRecords",
        "bedrock-agentcore:BatchUpdateMemoryRecords",
        "bedrock-agentcore:BatchDeleteMemoryRecords",
        "bedrock-agentcore:RetrieveMemoryRecords",
        "bedrock-agentcore:GetMemoryRecord",
        "bedrock-agentcore:DeleteMemoryRecord",
        "bedrock-agentcore:ListMemoryRecords"
      ],
      "Resource": "arn:aws:bedrock-agentcore:*:*:memory/*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceTag/tenant_id": "${aws:PrincipalTag/tenant_id}"
        }
      }
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
      "Action": ["sts:AssumeRole", "sts:TagSession"],
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "tenant-a"
        }
      }
    }
  ]
}
```

## BLOCKED の場合の代替案

`aws:ResourceTag/tenant_id` が Memory API で動作しない場合、以下の代替策を推奨します。

### 代替案 1: bedrock-agentcore:namespace Condition Key（推奨）

Example 02 で検証済みの `bedrock-agentcore:namespace` を使用する。
namespace パスにテナント ID を埋め込むことで、Record レベルのテナント分離を実現。

```json
{
  "Effect": "Allow",
  "Action": ["bedrock-agentcore:BatchCreateMemoryRecords"],
  "Resource": "arn:aws:bedrock-agentcore:*:*:memory/*",
  "Condition": {
    "StringLike": {
      "bedrock-agentcore:namespace": "/${aws:PrincipalTag/tenant_id}/*"
    }
  }
}
```

### 代替案 2: テナント別 Memory + Resource ARN 制限

テナントごとに個別の Memory リソースを作成し、
IAM ポリシーの Resource 句で Memory ARN を直接指定する。

### 代替案 3: 多層防御（namespace + ResourceTag）

namespace を主制御として使用し、将来 ResourceTag がサポートされた際に
多層防御として追加する。

## セキュリティのポイント

### 1. リソースタグの一致

Memory ResourceTag ABAC では、Memory リソースに設定された `tenant_id` タグと、
AssumeRole で付与された SessionTags の `tenant_id` が一致する場合のみ
アクセスを許可します。

### 2. アプリケーション層のバグでもブロック

仮にアプリケーション層で `tenant_id` の検証を誤っても、
IAM レベルでクロステナントアクセスがブロックされます。

### 3. Defense in Depth

- **Layer 1**: アプリケーション層での tenant_id 検証
- **Layer 2**: namespace Condition Key (Example 02)
- **Layer 3**: ResourceTag ABAC (この Example)

## 前提条件

- AWS CLI 設定済み（`aws configure`）
- Python 3.8+
- boto3 インストール済み
- AWS アカウントに以下の権限:
  - `bedrock-agentcore:CreateMemory`
  - `bedrock-agentcore:GetMemory`
  - `bedrock-agentcore:DeleteMemory`
  - `bedrock-agentcore:TagResource`
  - `bedrock-agentcore:ListTagsForResource`
  - `iam:CreateRole`
  - `iam:PutRolePolicy`
  - `iam:DeleteRole`
  - `sts:AssumeRole`

## 関連する Example

- **Example 02**: IAM ABAC (namespace Condition Key) - [OK] 動作確認済み
- **Example 05**: End-to-End (STS SessionTags)
- **Example 11**: S3 ABAC (s3:ExistingObjectTag/tenant_id) - リファレンス実装

## 参考資料

- [AWS IAM: Using tags to control access to and for IAM users and roles](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_iam-tags.html)
- [AWS IAM: Controlling access to AWS resources using resource tags](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_tags.html)
- [AWS Bedrock AgentCore Memory API](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-memory.html)
