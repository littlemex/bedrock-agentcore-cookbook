# IAM ABAC (Attribute-Based Access Control) with Memory API

このディレクトリには、AWS Bedrock AgentCore Memory API に対する IAM ABAC（属性ベースアクセス制御）の実装例が含まれています。

## 概要

IAM ABAC を使用すると、リソースタグと IAM プリンシパルタグを条件として、きめ細かなアクセス制御を実現できます。このサンプルでは、Memory API に対する ABAC の実装パターンを示します。

## ファイル構成

- `setup-iam-roles.py` - ABAC 用 IAM Role とポリシーのセットアップ
- `test-h1-condition-key.py` - `bedrock-agentcore: namespace` Condition Key の検証
- `test-actorId-condition-key.py` - `bedrock-agentcore: actorId` Condition Key の検証
- `H1_VERIFICATION_RESULT.md` - H-1 検証結果レポート（namespace）
- `ACTORID_VERIFICATION_RESULT.md` - actorId Condition Key 検証結果レポート
- `VERIFICATION_RESULT.md` - 全体的な検証結果レポート

## 検証した Condition Key

### [OK] bedrock-agentcore: namespace

Memory の namespace をもとにアクセス制御を行います。

**IAM Policy 例: **
```json
{
  "Effect": "Allow",
  "Action": "bedrock-agentcore: ListMemories",
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "bedrock-agentcore: namespace": "tenant-a"
    }
  }
}
```

このポリシーにより、`namespace=tenant-a` でタグ付けされた Memory のみアクセス可能になります。

## 前提条件

- AWS CLI 設定済み（`aws configure`）
- AWS アカウントに以下の権限
  - `iam: CreateRole`
  - `iam: CreatePolicy`
  - `iam: AttachRolePolicy`
  - `sts: AssumeRole`
  - `bedrock-agentcore: *`

## セットアップ

1. 依存パッケージのインストール

```bash
pip install -r ../../requirements.txt
```

2. IAM Role とポリシーの作成

```bash
python setup-iam-roles.py
```

実行すると以下が作成されます：
- ABAC 用 IAM Role
- Condition Key を使用した IAM Policy

3. Condition Key の検証

```bash
python test-h1-condition-key.py
```

このスクリプトは、`bedrock-agentcore: namespace` Condition Key が正常に動作するかを検証します。

## 検証結果

### [OK] bedrock-agentcore: namespace Condition Key

`bedrock-agentcore: namespace` Condition Key を使用した IAM Policy が正常に動作することを確認しました。

**検証内容: **
- namespace=tenant-a でタグ付けされた Memory へのアクセス: 成功
- namespace=tenant-b でタグ付けされた Memory へのアクセス: 拒否（期待通り）

詳細は `H1_VERIFICATION_RESULT.md` を参照してください。

### [BLOCKED] bedrock-agentcore: actorId Condition Key

`bedrock-agentcore: actorId` Condition Key を使用した IAM Policy は、**現時点では実質的に未サポート**です。

**検証内容: **
- actorId Condition Key 付き IAM ロールで Memory API を呼び出し
- 一致する actorId: AccessDeniedException（Null Condition により全拒否）
- 不一致の actorId: AccessDeniedException（同上）
- Condition Key なしの場合: 成功

**原因: **
Memory API が `actorId` のコンテキスト値を IAM に提供していないため、Condition Key の値が常に null となり、全てのリクエストが拒否される（Null Condition パターン）。

**代替策: **
namespace Condition Key を活用し、actorId を namespace パス内に埋め込む（例: `/tenant-a/actor-alice/`）ことで、間接的に actorId ベースの制御が可能。

詳細は `ACTORID_VERIFICATION_RESULT.md` を参照してください。

### Condition Key サポート状況まとめ

| Condition Key | 状態 | 備考 |
|--------------|------|------|
| `bedrock-agentcore: namespace` | [OK] サポート済み | IAM レベルで正常に機能 |
| `bedrock-agentcore: actorId` | [BLOCKED] 未サポート | API がコンテキスト値を提供しない |

## 重要な発見事項

当初、AWS 公式ドキュメントには `bedrock-agentcore: namespace` の記載がありませんでしたが、**実際には動作します**。この Condition Key は、マルチテナント環境でのアクセス制御に非常に有効です。

## 参考資料

- [AWS IAM Condition Keys ドキュメント](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-keys.html)
- [AWS Bedrock AgentCore ABAC パターン](https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_service-with-iam.html)
