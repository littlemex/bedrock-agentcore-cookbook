# Phase 13: AuthPolicyTable (DynamoDB)

> **[注意] E2E テスト未実施**: この Example は Zenn book の技術的主張を検証するためのリファレンス実装です。DynamoDB テーブル作成とクエリのローカル検証は完了していますが、Cognito Pre Token Generation Lambda との統合 E2E テストは未実施です。本番利用前に実環境での統合テストを行ってください。

Pre Token Generation Lambda 用の認証ポリシーテーブル実装。

## 概要

Cognito の Pre Token Generation Lambda トリガーが、JWT トークン発行時にユーザーの認証ポリシー情報を
DynamoDB から取得し、カスタムクレームとして注入するためのテーブル設計・運用スクリプト群。

## テーブル設計

### AuthPolicyTable

| 項目 | 値 |
|------|-----|
| テーブル名 | `AuthPolicyTable` |
| Partition Key | `email` (String) |
| BillingMode | `PAY_PER_REQUEST` |

### GSI: TenantIdIndex

| 項目 | 値 |
|------|-----|
| インデックス名 | `TenantIdIndex` |
| Partition Key | `tenant_id` (String) |
| Projection | `ALL` |

### 属性一覧

| 属性名 | 型 | 説明 |
|--------|-----|------|
| `email` | String | ユーザーのメールアドレス (PK) |
| `tenant_id` | String | テナント ID (GSI PK) |
| `role` | String | ユーザーロール (`admin`, `user`, `readonly`) |
| `groups` | List[String] | 所属グループ (`administrators`, `developers`, `viewers`) |
| `allowed_tools` | List[String] | 使用許可ツール (`*` で全許可) |
| `display_name` | String | 表示名 |
| `status` | String | ステータス (`active`, `inactive`) |

## アクセスパターン

1. **Email によるユーザーポリシー取得** (GetItem) - Pre Token Generation Lambda のメインクエリ
2. **テナント ID によるユーザー一覧取得** (Query on TenantIdIndex) - テナント管理用

## ファイル構成

```
examples/13-auth-policy-table/
  setup-dynamodb-table.py      # テーブル作成スクリプト
  seed-test-users.py           # テストユーザーデータ投入
  query-user-policy.py         # ユーザーポリシー取得 (検証用)
  phase13-config.json.example  # 設定ファイルテンプレート
  README.md                    # このファイル
```

## セットアップ手順

### 1. 設定ファイルの準備

```bash
cp phase13-config.json.example phase13-config.json
# 必要に応じて table_name, region を編集
```

### 2. テーブル作成

```bash
python3 setup-dynamodb-table.py
```

### 3. テストデータ投入

```bash
python3 seed-test-users.py
```

投入前にデータ内容を確認したい場合:

```bash
python3 seed-test-users.py --dry-run
```

### 4. 動作検証

Email でユーザーポリシーを取得:

```bash
python3 query-user-policy.py --email admin@tenant-a.example.com
```

テナント ID でユーザー一覧を取得 (GSI 検証):

```bash
python3 query-user-policy.py --tenant tenant-a
```

全ユーザー一覧:

```bash
python3 query-user-policy.py --list-all
```

Pre Token Generation Lambda のクレーム生成シミュレーション:

```bash
python3 query-user-policy.py --email admin@tenant-a.example.com --simulate-claims
```

JSON 出力:

```bash
python3 query-user-policy.py --email admin@tenant-a.example.com --json
```

## テストユーザー

| Email | Tenant | Role | Groups | Allowed Tools |
|-------|--------|------|--------|---------------|
| `admin@tenant-a.example.com` | tenant-a | admin | administrators, developers, viewers | `*` (全許可) |
| `user@tenant-a.example.com` | tenant-a | user | developers, viewers | code-review, documentation, testing |
| `admin@tenant-b.example.com` | tenant-b | admin | administrators, developers, viewers | `*` (全許可) |
| `readonly@tenant-b.example.com` | tenant-b | readonly | viewers | documentation |

## Pre Token Generation Lambda との連携

Pre Token Generation Lambda は以下のフローでこのテーブルを使用する:

1. Cognito がトークン発行時に Lambda をトリガー
2. Lambda が `event.request.userAttributes.email` を取得
3. AuthPolicyTable から `email` をキーにユーザーポリシーを取得 (GetItem)
4. 取得した `tenant_id`, `role`, `groups`, `allowed_tools` をカスタムクレームとして JWT に注入
5. API Gateway Authorizer が JWT のカスタムクレームを使って認可判定

## CDK 実装との関連

このスクリプト群は `cdk-agentcore-verification/lib/stack1-dynamodb.ts` の設計パターンを
AuthPolicyTable 用に特化したもの。CDK スタックでは Custom Resource Lambda でデータ投入を
行うが、ここではローカルスクリプトで同等の操作を提供する。

## 前提条件

- Python 3.12+
- boto3 (AWS SDK for Python)
- AWS 認証情報の設定 (`~/.aws/credentials` または環境変数)
- DynamoDB へのアクセス権限
