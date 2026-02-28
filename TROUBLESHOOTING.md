# トラブルシューティングガイド

このドキュメントでは、bedrock-agentcore-cookbook の examples を実行する際に頻繁に発生する問題と解決策をまとめています。

## 目次

1. [IAM 権限関連](#iam-権限関連)
2. [AWS API エラー](#aws-api-エラー)
3. [Python スクリプトエラー](#python-スクリプトエラー)
4. [リソース競合](#リソース競合)

---

## IAM 権限関連

### 1. sts:TagSession 権限不足 [CRITICAL]

**発生頻度**: 非常に高い（E2E テスト実行時に必ず発生）

**影響を受ける examples**:
- `examples/02-iam-abac` - Memory API の namespace ABAC
- `examples/11-s3-abac` - S3 オブジェクトタグ ABAC
- `examples/15-memory-resource-tag-abac` - Memory ResourceTag ABAC

**エラーメッセージ**:
```
botocore.exceptions.ClientError: An error occurred (AccessDenied) when calling the AssumeRole operation:
User: arn:aws:sts::776010787911:assumed-role/YOUR-ROLE-NAME/SESSION-NAME is not authorized to perform:
sts:TagSession on resource: arn:aws:iam::776010787911:role/TARGET-ROLE-NAME
```

**原因**:
- 現在の IAM ロール/ユーザーに `sts:TagSession` 権限がない
- セッションタグを使用した AssumeRole が拒否される
- ABAC（Attribute-Based Access Control）のテストができない

**解決策 1: IAM ポリシーを追加**（推奨）

現在の IAM ロール/ユーザーに以下のポリシーをアタッチしてください：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowAssumeRoleWithSessionTags",
      "Effect": "Allow",
      "Action": [
        "sts:AssumeRole",
        "sts:TagSession"
      ],
      "Resource": [
        "arn:aws:iam::*:role/*-abac-*",
        "arn:aws:iam::*:role/s3-abac-*",
        "arn:aws:iam::*:role/memory-abac-*"
      ]
    }
  ]
}
```

**AWS CLI での確認方法**:
```bash
# 現在のロールの権限を確認
aws iam get-role --role-name YOUR-ROLE-NAME

# ポリシーをアタッチ
aws iam put-role-policy \
  --role-name YOUR-ROLE-NAME \
  --policy-name AllowSessionTagging \
  --policy-document file://policy.json
```

**解決策 2: 管理者権限で実行**

AWS AdministratorAccess ポリシーを持つ IAM ユーザー/ロールで実行してください。

**解決策 3: セッションタグなしでテスト**（ABAC 検証不可）

各 example の Python スクリプトで `Tags` パラメータをコメントアウト：

```python
# examples/11-s3-abac/test-s3-abac.py の例
response = sts.assume_role(
    RoleArn=role_arn,
    RoleSessionName=session_name,
    # Tags=[  # この部分をコメントアウト
    #     {"Key": "tenant_id", "Value": tenant_id}
    # ]
)
```

**注意**: この場合、ABAC の検証はできません。

---

### 2. Bedrock AgentCore リソース作成権限不足

**影響を受ける examples**:
- `examples/01-memory-api` - Memory 作成
- `examples/03-gateway` - Gateway 作成
- `examples/04-policy-engine` - Policy Engine 作成

**エラーメッセージ**:
```
botocore.exceptions.ClientError: An error occurred (AccessDeniedException) when calling the CreateMemory operation:
User: arn:aws:sts::ACCOUNT_ID:assumed-role/ROLE_NAME/SESSION is not authorized to perform:
bedrock-agentcore:CreateMemory on resource: *
```

**解決策**:

以下のポリシーを追加してください：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:CreateMemory",
        "bedrock-agentcore:GetMemory",
        "bedrock-agentcore:DeleteMemory",
        "bedrock-agentcore:UpdateMemory",
        "bedrock-agentcore:ListMemories",
        "bedrock-agentcore:PutMemoryRecord",
        "bedrock-agentcore:RetrieveMemoryRecords",
        "bedrock-agentcore:DeleteMemoryRecord",
        "bedrock-agentcore:BatchDeleteMemoryRecords",
        "bedrock-agentcore:CreateGateway",
        "bedrock-agentcore:GetGateway",
        "bedrock-agentcore:DeleteGateway",
        "bedrock-agentcore:UpdateGateway",
        "bedrock-agentcore:CreatePolicyEngine",
        "bedrock-agentcore:GetPolicyEngine",
        "bedrock-agentcore:DeletePolicyEngine"
      ],
      "Resource": "*"
    }
  ]
}
```

---

### 3. S3 権限不足

**影響を受ける examples**:
- `examples/11-s3-abac`

**必要な権限**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:ListBucket",
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:PutObjectTagging",
        "s3:GetObjectTagging"
      ],
      "Resource": [
        "arn:aws:s3:::s3-abac-example-*",
        "arn:aws:s3:::s3-abac-example-*/*"
      ]
    }
  ]
}
```

---

### 4. IAM ロール作成権限不足

**影響を受ける examples**:
- `examples/02-iam-abac`
- `examples/11-s3-abac`
- `examples/12-gdpr-memory-deletion`
- `examples/15-memory-resource-tag-abac`

**必要な権限**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:GetRole",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:PassRole"
      ],
      "Resource": [
        "arn:aws:iam::*:role/*-abac-*",
        "arn:aws:iam::*:role/gdpr-*",
        "arn:aws:iam::*:role/s3-abac-*"
      ]
    }
  ]
}
```

---

## AWS API エラー

### 1. DynamoDB スキーマ不一致

**影響を受ける examples**:
- `examples/13-auth-policy-table`

**エラーメッセージ**:
```
botocore.exceptions.ClientError: An error occurred (ValidationException) when calling the BatchWriteItem operation:
The provided key element does not match the schema
```

**原因**:
既存の DynamoDB テーブルのキースキーマが、スクリプトの想定と異なる。

**解決策**:

```bash
# 既存テーブルを削除
aws dynamodb delete-table --table-name AuthPolicyTable --region us-east-1

# 新しいスクリプトでテーブルを再作成
cd examples/13-auth-policy-table
python3 setup-dynamodb-table.py --region us-east-1
```

---

### 2. リソース名の重複

**エラーメッセージ**:
```
botocore.exceptions.ClientError: An error occurred (ResourceAlreadyExistsException) when calling the CreateXXX operation:
Resource already exists
```

**解決策**:

各 example の `cleanup.py` または `cleanup-*.py` を実行してリソースを削除：

```bash
cd examples/11-s3-abac
python3 cleanup-s3-resources.py
```

または、設定ファイルでリソース名を変更：

```bash
cd examples/11-s3-abac
# phase11-config.json の bucket name を変更
```

---

## Python スクリプトエラー

### 1. boto3 クライアント名の間違い

**エラーメッセージ**:
```
AttributeError: 'AgentsforBedrockRuntime' object has no attribute 'create_gateway'
```

**解決策**:

```python
# NG
client = boto3.client('bedrock-agent-runtime')

# OK
client = boto3.client('bedrock-agentcore-control')
```

---

### 2. API パラメータ名の間違い

**エラーメッセージ**:
```
botocore.exceptions.ParamValidationError: Parameter validation failed:
Unknown parameter in input: "gatewayId", must be one of: gatewayIdentifier, ...
```

**解決策**:

```python
# NG
response = client.get_gateway(gatewayId="gw-xxx")

# OK
response = client.get_gateway(gatewayIdentifier="gw-xxx")
```

**API パラメータの正しい名前**:
| API | Get パラメータ | Create パラメータ |
|-----|---------------|------------------|
| Gateway | `gatewayIdentifier` | `name` |
| Target | `targetId` | `name` |
| Policy Engine | `policyEngineId` | `name` |

---

## リソース競合

### 1. 複数のテストスクリプトの同時実行

**問題**:
複数の example を並行して実行すると、リソース名が競合する場合があります。

**解決策**:

1. 各 example を順次実行する
2. または、設定ファイルでリソース名にユニークなサフィックスを追加：

```json
{
  "bucket": {
    "bucketName": "s3-abac-example-776010787911-test1"
  }
}
```

---

### 2. IAM ポリシーの伝播遅延

**問題**:
IAM ロールやポリシーを作成した直後にテストを実行すると、権限が反映されていない場合があります。

**解決策**:

各 example の `run-e2e-test.sh` では 10 秒の待機時間を設けていますが、それでも失敗する場合は待機時間を延長：

```bash
# run-e2e-test.sh の例
echo "[INFO] IAM ポリシー伝播を待機中 (30 秒)..."
sleep 30
```

---

## E2E テスト実行のベストプラクティス

### 前提条件の確認

E2E テストを実行する前に、以下を確認してください：

1. **IAM 権限**
   - `sts:TagSession` 権限があるか
   - Bedrock AgentCore リソース作成権限があるか
   - S3, DynamoDB, IAM の必要な権限があるか

2. **既存リソースの確認**
   - 同名のリソースが存在しないか
   - クリーンな環境で実行できるか

3. **設定ファイルの準備**
   - `phaseXX-config.json` を作成済みか
   - AWS アカウント ID が正しいか

### 推奨実行環境

1. **専用テスト環境**
   - 本番環境とは分離された AWS アカウント
   - 十分な IAM 権限を持つロール/ユーザー

2. **CI/CD パイプライン**
   - GitHub Actions 等での自動実行
   - テスト環境の自動セットアップ・クリーンアップ

3. **ローカル開発環境**
   - AWS CLI で適切なプロファイルを使用
   - 環境変数 `AWS_PROFILE` を設定

```bash
export AWS_PROFILE=test-environment
export AWS_REGION=us-east-1
cd examples/11-s3-abac
bash run-e2e-test.sh --region us-east-1
```

---

## よくある質問

### Q: sts:TagSession 権限はどのロールに必要ですか？

A: **テストを実行する側**の IAM ロール/ユーザーに必要です。AssumeRole される側（ターゲットロール）ではありません。

### Q: セッションタグなしでテストできますか？

A: テストは実行できますが、ABAC（属性ベースアクセス制御）の検証はできません。セッションタグによるテナント分離の動作確認が目的の場合、必ず `sts:TagSession` 権限を追加してください。

### Q: 本番環境でもセッションタグは必要ですか？

A: はい。マルチテナント環境で ABAC を使用する場合、アプリケーションが AssumeRole する際にセッションタグを設定する必要があります。そのため、アプリケーションの IAM ロールに `sts:TagSession` 権限が必要です。

---

## サポート

問題が解決しない場合は、以下を確認してください：

1. [README.md](README.md) のトラブルシューティングセクション
2. [E2E_TEST_GUIDE.md](E2E_TEST_GUIDE.md) のテスト実行手順
3. 各 example の README.md

それでも解決しない場合は、GitHub Issues にて報告してください：
https://github.com/littlemex/bedrock-agentcore-cookbook/issues

---

**最終更新**: 2026-02-28
**対応バージョン**: examples/01-15
