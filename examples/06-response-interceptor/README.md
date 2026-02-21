# 06: Response Interceptor

AgentCore Gateway の Response Interceptor の実装例です。MCP サーバーからの `tools/list` レスポンスを受け取り、JWT トークンのロールに基づいてツールリストをフィルタリング (RBAC) します。

## 概要

Response Interceptor は、Gateway が MCP サーバーからのレスポンスをクライアントに返却する前に介入する Lambda 関数です。以下の用途に使用できます：

- ロールベースのツールフィルタリング (RBAC)
- レスポンスの加工・拡張
- ログ収集

## ファイル構成

```
06-response-interceptor/
├── README.md                           # このファイル
├── lambda_function.py                  # Response Interceptor Lambda 関数
├── deploy-response-interceptor.py      # デプロイスクリプト
├── verify-response-interceptor.py      # 検証スクリプト
└── VERIFICATION_RESULT.md              # 検証結果レポート
```

## 前提条件

- AWS CLI 設定済み
- Python 3.9+
- boto3 >= 1.42.0
- Gateway が作成済み (examples/03-gateway)

## Response Interceptor のイベント構造

```json
{
  "mcp": {
    "gatewayResponse": {
      "headers": { "Content-Type": "application/json" },
      "body": {
        "jsonrpc": "2.0",
        "result": { "tools": [...] },
        "id": 1
      }
    },
    "gatewayRequest": {
      "headers": {
        "authorization": "Bearer <JWT_TOKEN>"
      }
    }
  }
}
```

**重要**: Authorization ヘッダーは `gatewayRequest.headers` から取得する必要があります。`gatewayResponse.headers` にはクライアントが送信した Authorization は含まれません。

## 返却構造

```json
{
  "interceptorOutputVersion": "1.0",
  "mcp": {
    "transformedGatewayResponse": {
      "headers": { "Content-Type": "application/json" },
      "body": {
        "jsonrpc": "2.0",
        "result": { "tools": [...] },
        "id": 1
      }
    }
  }
}
```

## RBAC ルール

| ロール | 許可されるツール | 説明 |
|--------|-----------------|------|
| admin | `*` (全ツール) | 管理者は全ツールにアクセス可能 |
| user | `retrieve_doc`, `list_tools` | 一般ユーザーは参照系のみ |
| guest | (なし) | ゲストはツールを使用不可 |
| (未知のロール) | (なし) | fail-closed: デフォルトで全拒否 |

## 使い方

### 1. ローカル検証

```bash
python3 verify-response-interceptor.py
```

### 2. デプロイ

```bash
python3 deploy-response-interceptor.py
```

### 3. リモート検証

```bash
python3 verify-response-interceptor.py --remote
```

## Gateway への設定

`update_gateway` API の `interceptorConfigurations` パラメータを使用します：

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
            "interceptor": {
                "lambda": {
                    "arn": lambda_arn,
                }
            },
            "interceptionPoints": ["RESPONSE"],
        }
    ],
)
```

### interceptorConfigurations のスキーマ

```
interceptorConfigurations[]:
  interceptor:
    lambda:
      arn: string (Lambda ARN)
  interceptionPoints: list[string] ("REQUEST" | "RESPONSE")
  inputConfiguration:
    passRequestHeaders: boolean
```

## 設計上の注意点

### fail-closed 設計

JWT の検証に失敗した場合やロールが不明な場合、空のツールリスト `{"tools": []}` を返却します。これにより、認証情報が不正な場合にツール情報が漏洩することを防ぎます。

### JSON-RPC 準拠

fail-closed レスポンスでも `jsonrpc`, `result`, `id` フィールドを含む完全な JSON-RPC 構造を返却します。

### ツール名のパース

Gateway のツール名は `{target}___{toolName}` 形式です。フィルタリング時はツール名部分のみで判定します。

## 参考資料

- AWS 公式サンプル: `01-tutorials/02-AgentCore-gateway/09-fine-grained-access-control/`
- Zenn book: `books/agentcore-verification/04-response-interceptor.md`
