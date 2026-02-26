# AgentCore Gateway E2E Verification Stack

このディレクトリは、書籍の CRITICAL alert 項目を E2E 検証するための AWS CDK スタックです。

## 検証対象

### 1. Chapter 13: Cedar Deny 後の Interceptor 実行（最優先）

**検証項目**:
- AgentCore Gateway の ENFORCE モードで、Cedar Policy Engine が Deny を返した後、Request Interceptor が実行されるか

**検証シナリオ**:
1. Private Sharing リソース（agent-private）を作成
2. Cedar ポリシーで所有者と Public のみ permit、Private は deny-by-default
3. 非共有テナント（tenant-c）が agent-private にアクセス → Cedar は Deny を返す
4. Request Interceptor のログを確認 → 実行されたか？
5. 共有先テナント（tenant-b）が agent-private にアクセス → Request Interceptor が DynamoDB 確認後に Allow

**期待結果**:
- Cedar Deny 後も Interceptor が実行される → 本章の設計は有効
- Cedar Deny で終了 → 代替設計（Cedar Set 型または LOG_ONLY モード）が必要

### 2. Chapter 5: Cedar JWT → principal 属性マッピング

**検証項目**:
- JWT の `tenant_id`, `role` クレームが Cedar の `principal.tenant_id`, `principal.role` として参照可能か

**検証シナリオ**:
1. JWT に `tenant_id: tenant-a`, `role: admin` を含める
2. Cedar ポリシーで `principal.tenant_id == "tenant-a" && principal.role == "admin"` を条件とする
3. tools/call リクエストを送信
4. CloudWatch Logs で Cedar 評価結果を確認

**期待結果**:
- Cedar ポリシーが正しく評価される → Chapter 5 の設計は有効

### 3. Chapter 6: Interceptor レスポンス構造

**検証項目**:
- Request Interceptor の `transformedGatewayResponse` がクライアントに正しく中継されるか

**検証シナリオ**:
1. Request Interceptor で拒否レスポンスを返す
2. クライアント側で受信するレスポンスの形式を確認

**期待結果**:
- `interceptorOutputVersion: "1.0"` が正式仕様
- `body` は dict 型で受け付ける

## アーキテクチャ

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ Bearer Token
       ▼
┌──────────────────┐
│  API Gateway     │
│  + Lambda Auth   │
└──────┬───────────┘
       │ Validated JWT
       ▼
┌────────────────────────┐
│  AgentCore Gateway     │
│  ┌──────────────────┐  │
│  │ Cedar Policy     │  │
│  │ Engine           │  │
│  └──────┬───────────┘  │
│         │ Deny/Allow   │
│         ▼              │
│  ┌──────────────────┐  │
│  │ Request          │  │
│  │ Interceptor      │  │
│  └──────┬───────────┘  │
│         │              │
└─────────┼──────────────┘
          │
          ▼
     ┌─────────┐
     │   MCP   │
     │ Server  │
     └─────────┘
```

## デプロイ手順

### 前提条件

- AWS CLI 設定済み
- Node.js 18+ インストール
- AWS CDK CLI インストール済み

```bash
npm install -g aws-cdk
```

### 1. 依存関係のインストール

```bash
cd e2e-verification/cdk-agentcore-gateway
npm install
```

### 2. CDK ブートストラップ（初回のみ）

```bash
cdk bootstrap
```

### 3. デプロイ

```bash
cdk deploy
```

### 4. テスト実行

```bash
npm run test:chapter13
npm run test:chapter5
npm run test:chapter6
```

## スタック構成

### Cognito Stack
- User Pool
- App Client
- Test Users (tenant-a admin, tenant-b user, tenant-c user)
- Pre Token Generation Lambda V2

### DynamoDB Stack
- Sharing Table (Chapter 13 用)
- Tenants Table

### AgentCore Gateway Stack
- Gateway
- Cedar Policy Store
- Lambda Authorizer
- Request Interceptor Lambda
- Response Interceptor Lambda

### Test MCP Server Stack
- Lambda 関数として実装された簡易 MCP サーバー
- tools/list, tools/call をサポート

## 検証結果の記録

各検証の結果は以下に記録：

- `results/chapter13-cedar-deny-interceptor.md`
- `results/chapter5-cedar-jwt-mapping.md`
- `results/chapter6-interceptor-response.md`

## クリーンアップ

```bash
cdk destroy
```

## トラブルシューティング

### AgentCore Gateway が利用できない場合

AgentCore Gateway が Preview または GA 前の場合、以下の簡易検証環境を使用：

1. **Cedar スタンドアロン検証**: Cedar CLI で Cedar ポリシーのみを検証
2. **Lambda 単体検証**: Interceptor Lambda を直接 invoke してイベント構造を確認
3. **API Gateway Mock**: API Gateway で Gateway の代替として動作確認

これらの制限付き検証でも、書籍の設計の妥当性を部分的に確認可能。
