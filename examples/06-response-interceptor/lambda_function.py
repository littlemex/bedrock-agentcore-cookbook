"""
Response Interceptor Lambda Function

AgentCore Gateway の Response Interceptor として動作する Lambda 関数。
MCP サーバーからのレスポンス (tools/list) を受け取り、
JWT トークンのロールに基づいてツールリストをフィルタリングする (RBAC)。

Response Interceptor のイベント構造:
  {
    "mcp": {
      "gatewayResponse": {
        "headers": { ... },
        "body": { "jsonrpc": "2.0", "result": { "tools": [...] }, "id": 1 }
      },
      "gatewayRequest": {
        "headers": { "authorization": "Bearer <JWT_TOKEN>" }
      }
    }
  }

返却構造:
  {
    "interceptorOutputVersion": "1.0",
    "mcp": {
      "transformedGatewayResponse": {
        "headers": { ... },
        "body": { ... }
      }
    }
  }
"""

import json
import logging
import base64

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Role-based permissions (RBAC)
# 本番環境では DynamoDB 等の外部 DB から取得することを推奨
ROLE_PERMISSIONS = {
    "admin": ["*"],
    "user": ["retrieve_doc", "list_tools"],
    "guest": [],
}


def extract_role_from_jwt(token):
    """JWT トークンから role クレームを抽出する (base64 デコード)。

    本番環境では PyJWT + JWKS による署名検証を推奨。
    このサンプルでは検証用途として payload のデコードのみ実施。
    """
    try:
        if token.startswith("Bearer "):
            token = token[7:]

        parts = token.split(".")
        if len(parts) != 3:
            logger.warning("Invalid JWT format: expected 3 parts, got %d", len(parts))
            return None

        payload = parts[1]
        # base64url のパディング追加
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)

        role = claims.get("role", "guest")
        logger.info("Extracted role from JWT: %s", role)
        return role

    except Exception as e:
        logger.warning("Failed to extract role from JWT: %s", e)
        return None


def filter_tools(tools, role):
    """ロールに基づいてツールリストをフィルタリングする。

    Args:
        tools: ツール辞書のリスト
        role: ユーザーのロール文字列

    Returns:
        フィルタリング済みのツールリスト
    """
    allowed = ROLE_PERMISSIONS.get(role, [])
    if not allowed:
        return []
    if "*" in allowed:
        return tools

    filtered = []
    for tool in tools:
        gateway_name = tool.get("name", "")
        # Gateway のツール名は "{target}___{toolName}" 形式
        tool_name = gateway_name.split("___")[-1] if "___" in gateway_name else gateway_name
        if tool_name in allowed:
            filtered.append(tool)

    return filtered


def lambda_handler(event, context):
    """Response Interceptor の Lambda ハンドラー。"""
    logger.info("Response Interceptor invoked")
    logger.info("Event: %s", json.dumps(event, default=str))

    try:
        mcp_data = event.get("mcp", {})
        gateway_response = mcp_data.get("gatewayResponse", {})
        gateway_request = mcp_data.get("gatewayRequest", {})

        # Authorization ヘッダーは gatewayRequest から取得する（重要）
        # gatewayResponse.headers には Authorization は含まれない
        request_headers = gateway_request.get("headers", {})
        response_headers = gateway_response.get("headers", {})
        response_body = gateway_response.get("body", {})

        # ケースインセンシティブな Authorization ヘッダー取得
        auth_header = None
        for key, value in request_headers.items():
            if key.lower() == "authorization":
                auth_header = value
                break

        logger.info("Authorization header present: %s", bool(auth_header))

        # tools/list レスポンスかどうか判定
        result = {}
        if isinstance(response_body, dict):
            result = response_body.get("result", {})

        tools = result.get("tools", [])

        if not tools:
            # ツールリストでない場合はそのまま通過
            logger.info("Not a tools/list response, passing through")
            return {
                "interceptorOutputVersion": "1.0",
                "mcp": {
                    "transformedGatewayResponse": {
                        "headers": response_headers,
                        "body": response_body,
                    }
                },
            }

        # JWT からロールを取得
        role = None
        if auth_header:
            role = extract_role_from_jwt(auth_header)

        if not role:
            logger.warning("No role found, denying all tools (fail-closed)")
            denied_body = {
                "jsonrpc": "2.0",
                "result": {"tools": []},
                "id": response_body.get("id"),
            }
            return {
                "interceptorOutputVersion": "1.0",
                "mcp": {
                    "transformedGatewayResponse": {
                        "headers": {"Content-Type": "application/json"},
                        "body": denied_body,
                    }
                },
            }

        # ツールフィルタリング
        filtered_tools = filter_tools(tools, role)

        logger.info(
            "Filtered tools: original=%d, filtered=%d, role=%s",
            len(tools),
            len(filtered_tools),
            role,
        )

        # レスポンスを構築
        filtered_body = {
            "jsonrpc": response_body.get("jsonrpc", "2.0"),
            "result": {"tools": filtered_tools},
            "id": response_body.get("id"),
        }

        return {
            "interceptorOutputVersion": "1.0",
            "mcp": {
                "transformedGatewayResponse": {
                    "headers": response_headers,
                    "body": filtered_body,
                }
            },
        }

    except Exception as e:
        logger.error("Response Interceptor error: %s", e)
        # fail-closed: エラー時は空のツールリストを返却
        error_body = {
            "jsonrpc": "2.0",
            "result": {"tools": []},
            "id": 1,
        }
        return {
            "interceptorOutputVersion": "1.0",
            "mcp": {
                "transformedGatewayResponse": {
                    "headers": {"Content-Type": "application/json"},
                    "body": error_body,
                }
            },
        }
