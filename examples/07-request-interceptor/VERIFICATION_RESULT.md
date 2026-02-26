# Request Interceptor 検証結果

検証日: 2026-02-21
検証者: Claude Opus 4.6
Gateway ID: e2e-phase3-gateway-sytqnigmll

---

## 検証サマリー

| 項目 | 結果 |
|------|------|
| ローカル検証 | 11 PASS / 0 FAIL |
| Lambda デプロイ | PASS |
| Lambda リモート呼び出し | 4 PASS / 0 FAIL |
| Gateway Interceptor 設定 | PASS |
| **総合判定** | **PASS** |

---

## 1. Lambda 関数のデプロイ

| 項目 | 値 |
|------|---|
| 関数名 | `e2e-request-interceptor` |
| ARN | `arn: aws: lambda: us-east-1:123456789012: function: e2e-request-interceptor` |
| ランタイム | Python 3.12 |
| IAM ロール | `e2e-request-interceptor-role` |
| Gateway 呼び出し権限 | 設定済み |

---

## 2. ローカル検証結果

| # | テスト名 | 期待 | 結果 |
|---|---------|------|------|
| 1 | initialize: バイパス | 通過 | PASS |
| 2 | ping: バイパス | 通過 | PASS |
| 3 | tools/list: バイパス | 通過 | PASS |
| 4 | admin + retrieve_doc | 通過 | PASS |
| 5 | admin + delete_data_source | 通過 | PASS |
| 6 | user + retrieve_doc | 通過 | PASS |
| 7 | user + delete_data_source | 拒否 | PASS |
| 8 | guest + retrieve_doc | 拒否 | PASS |
| 9 | JWT なし | 拒否 | PASS |
| 10 | 不正 JWT | 拒否 | PASS |
| 11 | システムツール | 通過 | PASS |

---

## 3. Lambda リモート呼び出し検証

| # | テスト名 | 結果 |
|---|---------|------|
| 1 | initialize: bypass | PASS |
| 2 | admin + delete_data_source: allow | PASS |
| 3 | user + delete_data_source: deny | PASS |
| 4 | no auth: deny | PASS |

---

## 4. Gateway への Interceptor 設定

### 設定方法

`update_gateway` API の `interceptorConfigurations` パラメータで、Request と Response の両方の Interceptor を同時に設定:

```python
interceptorConfigurations=[
    {
        "interceptor": {"lambda": {"arn": request_lambda_arn}},
        "interceptionPoints": ["REQUEST"],
    },
    {
        "interceptor": {"lambda": {"arn": response_lambda_arn}},
        "interceptionPoints": ["RESPONSE"],
    },
]
```

### 設定結果

```
update_gateway: SUCCESS
Gateway: UPDATING -> READY
Both REQUEST and RESPONSE interceptors configured
```

---

## 5. 重要な発見事項

### 5.1 Request Interceptor と Response Interceptor の同時設定

`interceptorConfigurations` はリスト形式であり、複数の Interceptor を同時に設定できる。`interceptionPoints` フィールドで `REQUEST` と `RESPONSE` を区別する。

### 5.2 拒否レスポンスの構造

Request Interceptor がリクエストを拒否する場合、`transformedGatewayResponse` を返却する。この場合、リクエストは MCP サーバーに到達せず、クライアントに直接エラーレスポンスが返却される。

AWS 公式サンプル (interceptor-request.py) の `_deny_request()` 関数でも同じパターンが使用されている:

```python
{
    "interceptorOutputVersion": "1.0",
    "mcp": {
        "transformedGatewayResponse": {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": message}]
                }
            }
        }
    }
}
```

### 5.3 MCP ライフサイクルメソッドのバイパス

`initialize`, `notifications/initialized`, `ping`, `tools/list` は認可処理をバイパスする必要がある。これらのメソッドはデータアクセスを伴わないプロトコル必須のハンドシェイクである。

---

## 6. 検証で使用した AWS リソース

| リソース | 種別 | ARN/ID |
|---------|------|--------|
| Lambda | Function | `arn: aws: lambda: us-east-1:123456789012: function: e2e-request-interceptor` |
| IAM Role | Role | `arn: aws: iam::123456789012: role/e2e-request-interceptor-role` |
| Gateway | AgentCore Gateway | `e2e-phase3-gateway-sytqnigmll` |

---

検証完了日: 2026-02-21
