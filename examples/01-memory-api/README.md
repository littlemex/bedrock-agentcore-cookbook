# AWS Bedrock AgentCore Memory API Examples

このディレクトリには、AWS Bedrock AgentCore Memory API の基本的な使い方を示すサンプルコードが含まれています。

## 概要

Memory API を使用すると、エージェントの会話履歴やコンテキストを永続化し、次回の会話で参照できます。

## ファイル構成

- `setup-memory.py` - Memory の作成とセットアップ
- `setup-memory-multi-tenant.py` - マルチテナント環境での Memory セットアップ
- `test-memory-complete.py` - Memory API 完全検証スクリプト（NEW）
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

4. Memory API 完全検証の実行（NEW）

```bash
python test-memory-complete.py
```

このスクリプトは以下を検証します：

**Test 1: Memory ACTIVE 状態の確認**
- Memory 作成後、ACTIVE 状態になるまで待機
- 最大 60 秒待機、5 秒間隔でステータス確認

**Test 2: Memory Record の create → wait → retrieve フロー**
- tenant-a で Memory Record 作成
- ベクトルインデックス構築待機（30 秒）
- tenant-a で Memory Record 検索
- 自テナントのデータが取得できることを確認（正のテスト）

**Test 3: DeleteMemoryRecord の Cross-Tenant アクセス拒否**
- tenant-b で tenant-a の Record 削除を試行
- AccessDenied が返されることを確認

**Test 4: UpdateMemoryRecord の Cross-Tenant アクセス拒否**
- tenant-b で tenant-a の Record 更新を試行
- AccessDenied が返されることを確認

**Test 5: tenant-a で自 Record 削除（クリーンアップ）**
- tenant-a は自分の Record を削除できることを確認

前提条件:
- Memory リソースが作成済み（`setup-memory.py` または `setup-memory-multi-tenant.py`）
- IAM Role が設定済み（tenant-a, tenant-b 用）
- phase5-config.json が存在する

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
