"""
Request Interceptor Lambda Function

AgentCore Gateway の Request Interceptor として動作する Lambda 関数。
クライアントから MCP サーバーへのリクエストを検査し、
JWT トークンに基づいてツール呼び出しの認可を行う。

Request Interceptor のイベント構造:
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
          "params": { "name": "target___tool_name", "arguments": {...} },
          "id": 1
        }
      }
    }
  }

返却構造 (通過):
  {
    "interceptorOutputVersion": "1.0",
    "mcp": {
      "transformedGatewayRequest": {
        "headers": { ... },
        "body": { ... }
      }
    }
  }

返却構造 (拒否):
  {
    "interceptorOutputVersion": "1.0",
    "mcp": {
      "transformedGatewayResponse": {
        "statusCode": 200,
        "headers": { "Content-Type": "application/json" },
        "body": {
          "jsonrpc": "2.0",
          "id": <rpc_id>,
          "result": {
            "isError": true,
            "content": [{ "type": "text", "text": "<error_message>" }]
          }
        }
      }
    }
  }
"""

import base64
import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# MCP ライフサイクルメソッド -- 認可処理をバイパス
MCP_LIFECYCLE_METHODS = {
    "initialize",
    "notifications/initialized",
    "ping",
    "tools/list",
}

# AgentCore システムツール -- 認可不要
SYSTEM_TOOLS = {"x_amz_bedrock_agentcore_search"}

# ロール別のツール呼び出し権限
ROLE_TOOL_PERMISSIONS = {
    "admin": ["*"],
    "user": ["retrieve_doc", "list_tools"],
    "guest": [],
}


def extract_claims_from_jwt(token):
    """JWT トークンから claims を抽出する (base64 デコード)。

    本番環境では PyJWT + JWKS による署名検証を推奨。
    """
    try:
        if token.startswith("Bearer "):
            token = token[7:]

        parts = token.split(".")
        if len(parts) != 3:
            logger.warning("Invalid JWT format: expected 3 parts, got %d", len(parts))
            return None

        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        return claims

    except Exception as e:
        logger.warning("Failed to extract claims from JWT: %s", e)
        return None


def is_tool_allowed(tool_name, role):
    """ツール呼び出しが許可されているか確認する。"""
    allowed = ROLE_TOOL_PERMISSIONS.get(role, [])
    if not allowed:
        return False
    if "*" in allowed:
        return True
    return tool_name in allowed


def _allow_request(headers, body):
    """リクエストを通過させるレスポンスを生成する。"""
    return {
        "interceptorOutputVersion": "1.0",
        "mcp": {
            "transformedGatewayRequest": {
                "headers": headers,
                "body": body,
            }
        },
    }


def _deny_request(rpc_id, message):
    """リクエストを拒否するレスポンスを生成する (MCP JSON-RPC 準拠)。"""
    logger.warning("Denying request: %s", message)
    return {
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
                        "content": [
                            {"type": "text", "text": message}
                        ],
                    },
                },
            }
        },
    }


def lambda_handler(event, context):
    """Request Interceptor の Lambda ハンドラー。"""
    logger.info("Request Interceptor invoked")
    logger.info("Event: %s", json.dumps(event, default=str))

    try:
        mcp_data = event.get("mcp", {})
        gateway_request = mcp_data.get("gatewayRequest", {})
        headers = gateway_request.get("headers", {})
        body = gateway_request.get("body", {})

        # body が文字列の場合は JSON パース
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError as e:
                logger.error("Invalid JSON in request body: %s", e)
                return _deny_request(None, "Invalid JSON in request body")

        # JSON-RPC メソッドとIDを取得
        method = body.get("method", "")
        rpc_id = body.get("id")

        logger.info("Method: %s, RPC ID: %s", method, rpc_id)

        # MCP ライフサイクルメソッドはバイパス
        if method in MCP_LIFECYCLE_METHODS:
            logger.info("Lifecycle method '%s', passing through", method)
            return _allow_request(headers, body)

        # Authorization ヘッダーを取得 (ケースインセンシティブ)
        auth_header = None
        for key, value in headers.items():
            if key.lower() == "authorization":
                auth_header = value
                break

        if not auth_header:
            logger.warning("No Authorization header found")
            return _deny_request(rpc_id, "Authorization required")

        # JWT から claims を取得
        claims = extract_claims_from_jwt(auth_header)
        if not claims:
            logger.warning("Failed to extract claims from JWT")
            return _deny_request(rpc_id, "Invalid authorization token")

        role = claims.get("role", "guest")
        tenant_id = claims.get("tenant_id", "")
        user_id = claims.get("sub", "")

        logger.info("Role: %s, Tenant: %s, User: %s", role, tenant_id, user_id)

        # tools/call の場合はツール呼び出し権限を検査
        if method == "tools/call":
            params = body.get("params", {})
            tool_name = params.get("name", "")

            # Gateway のツール名形式 ({target}___{toolName}) からツール名を抽出
            actual_tool_name = tool_name.split("___")[-1] if "___" in tool_name else tool_name

            # システムツールはバイパス
            if actual_tool_name in SYSTEM_TOOLS:
                logger.info("System tool '%s', passing through", actual_tool_name)
                return _allow_request(headers, body)

            # ロールベースのツール呼び出し権限チェック
            if not is_tool_allowed(actual_tool_name, role):
                logger.warning(
                    "Tool '%s' not allowed for role '%s'", actual_tool_name, role
                )
                return _deny_request(
                    rpc_id,
                    f"Access denied: tool '{actual_tool_name}' is not allowed for role '{role}'"
                )

            logger.info("Tool '%s' allowed for role '%s'", actual_tool_name, role)

        # その他のメソッドはそのまま通過
        return _allow_request(headers, body)

    except Exception as e:
        logger.error("Request Interceptor error: %s", e)
        return _deny_request(None, "Authorization failed")
