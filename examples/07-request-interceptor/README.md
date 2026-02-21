# 07: Request Interceptor

AgentCore Gateway の Request Interceptor の実装例です。クライアントから MCP サーバーへのリクエストを検査し、JWT トークンのロールに基づいてツール呼び出しの認可を行います。

## 概要

Request Interceptor は、Gateway がクライアントからのリクエストを MCP サーバーに転送する前に介入する Lambda 関数です。以下の用途に使用できます：

- ツール呼び出しの認可チェック (RBAC)
- リクエストの加工・拡張
- テナント境界の制御
- Memory アクセスの認可

## ファイル構成

```
07-request-interceptor/
├── README.md                           # このファイル
├── lambda_function.py                  # Request Interceptor Lambda 関数
├── deploy-request-interceptor.py       # デプロイスクリプト
├── verify-request-interceptor.py       # 検証スクリプト
└── VERIFICATION_RESULT.md              # 検証結果レポート
```

## Request Interceptor のイベント構造

```json
{
  "mcp": {
    "gatewayRequest": {
      "headers": {
        "authorization": "Bearer <JWT_TOKEN>",
        "content-type": "application/json"
      },
      "body": {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
          "name": "target___tool_name",
          "arguments": { ... }
        },
        "id": 1
      }
    }
  }
}
```

## 返却構造

### リクエスト通過 (allow)

```json
{
  "interceptorOutputVersion": "1.0",
  "mcp": {
    "transformedGatewayRequest": {
      "headers": { ... },
      "body": { ... }
    }
  }
}
```

### リクエスト拒否 (deny)

```json
{
  "interceptorOutputVersion": "1.0",
  "mcp": {
    "transformedGatewayResponse": {
      "statusCode": 200,
      "headers": { "Content-Type": "application/json" },
      "body": {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
          "isError": true,
          "content": [{ "type": "text", "text": "Access denied: ..." }]
        }
      }
    }
  }
}
```

**重要**: 拒否する場合は `transformedGatewayRequest` ではなく `transformedGatewayResponse` を返却します。これにより、MCP サーバーにリクエストが到達することなくクライアントにエラーを返却できます。

## 認可ロジック

### MCP ライフサイクルメソッドのバイパス

以下のメソッドは認可チェックなしで通過します：

- `initialize` -- MCP セッション確立
- `notifications/initialized` -- セッション確立通知
- `ping` -- ヘルスチェック
- `tools/list` -- ツール一覧取得

### システムツールのバイパス

AgentCore 組み込みの `x_amz_bedrock_agentcore_search` ツールは認可不要です。

### ロール別のツール呼び出し権限

| ロール | 許可されるツール | 説明 |
|--------|-----------------|------|
| admin | `*` (全ツール) | 管理者は全ツールを呼び出し可能 |
| user | `retrieve_doc`, `list_tools` | 一般ユーザーは参照系のみ |
| guest | (なし) | ゲストはツール呼び出し不可 |

## 使い方

### 1. ローカル検証

```bash
python3 verify-request-interceptor.py
```

### 2. デプロイ

```bash
python3 deploy-request-interceptor.py
```

### 3. リモート検証

```bash
python3 verify-request-interceptor.py --remote
```

## Gateway への設定

`update_gateway` API の `interceptorConfigurations` で `interceptionPoints: ["REQUEST"]` を指定します：

```python
client.update_gateway(
    gatewayIdentifier=gateway_id,
    name=gateway_name,
    roleArn=role_arn,
    protocolType="MCP",
    authorizerType="CUSTOM_JWT",
    authorizerConfiguration={...},
    interceptorConfigurations=[
        {
            "interceptor": {"lambda": {"arn": request_lambda_arn}},
            "interceptionPoints": ["REQUEST"],
        },
        {
            "interceptor": {"lambda": {"arn": response_lambda_arn}},
            "interceptionPoints": ["RESPONSE"],
        },
    ],
)
```

## 参考資料

- AWS 公式サンプル: `02-use-cases/site-reliability-agent-workshop/lab_helpers/lab_03/interceptor-request.py`
- Zenn book: `books/agentcore-verification/05-request-interceptor.md`
