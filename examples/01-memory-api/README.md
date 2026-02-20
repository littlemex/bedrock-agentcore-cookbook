# AWS Bedrock AgentCore Memory API Examples

このディレクトリには、AWS Bedrock AgentCore Memory API の基本的な使い方を示すサンプルコードが含まれています。

## 概要

Memory API を使用すると、エージェントの会話履歴やコンテキストを永続化し、次回の会話で参照できます。

## ファイル構成

- `setup-memory.py` - Memory の作成とセットアップ
- `setup-memory-multi-tenant.py` - マルチテナント環境での Memory セットアップ
- `cleanup.py` - 作成したリソースのクリーンアップ
- `VERIFICATION_RESULT.md` - 検証結果レポート

## 前提条件

- AWS CLI 設定済み（`aws configure`）
- AWS アカウントに以下の権限
  - `bedrock-agentcore: CreateMemory`
  - `bedrock-agentcore: GetMemory`
  - `bedrock-agentcore: DeleteMemory`
  - `iam: CreateRole`
  - `iam: AttachRolePolicy`

## セットアップ

1. 依存パッケージのインストール

```bash
pip install -r ../../requirements.txt
```

2. Memory の作成

```bash
python setup-memory.py
```

実行すると以下が作成されます：
- Memory リソース
- 必要な IAM Role とポリシー

3. マルチテナント設定（オプション）

```bash
python setup-memory-multi-tenant.py
```

## クリーンアップ

作成したリソースを削除するには：

```bash
python cleanup.py
```

## 検証結果

検証結果の詳細は `VERIFICATION_RESULT.md` を参照してください。

## 参考資料

- [AWS Bedrock AgentCore Memory API ドキュメント](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-memory.html)
- [AWS Bedrock AgentCore 公式サンプル](https://github.com/aws-samples/amazon-bedrock-agentcore-samples)
