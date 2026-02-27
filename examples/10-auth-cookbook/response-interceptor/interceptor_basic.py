"""
Response Interceptor for AgentCore Gateway (Chapter 6)

Response Interceptorは以下を実施します:
- ツールフィルタリング（RBAC）
- tools/listとSemantic Searchの両レスポンス対応
- fail-closed設計
"""

import json
import logging
import os

import jwt

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 環境変数
JWKS_URL = os.environ.get("JWKS_URL", "")
CLIENT_ID = os.environ.get("CLIENT_ID", "")

# グローバルスコープで初期化（ウォームスタート時にキャッシュ再利用）
jwks_client = jwt.PyJWKClient(JWKS_URL) if JWKS_URL else None

ROLE_PERMISSIONS = {
    "admin": ["*"],
    "user": ["retrieve_doc", "search_memory"],
    "guest": [],
}


def decode_jwt_payload(token):
    """JWT署名を検証してclaimsを取得"""
    if jwks_client:
        # 本番環境: PyJWT + JWKS署名検証
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=CLIENT_ID,
            options={"require": ["exp", "token_use"]},
        )
        return claims
    else:
        # 開発環境のみ: 警告を出力
        logger.warning("JWKS_URL not set - JWT validation disabled")
        raise ValueError("JWKS_URL not configured")


def filter_tools(tools, role):
    """ロールに基づいてツール一覧をフィルタリング"""
    allowed = ROLE_PERMISSIONS.get(role, [])
    if not allowed:
        return []
    if "*" in allowed:
        return tools
    filtered = []
    for tool in tools:
        name = tool.get("name", "")
        tool_name = name.split("___")[-1] if "___" in name else name
        if tool_name in allowed:
            filtered.append(tool)
    return filtered


def lambda_handler(event, context):
    """Response Interceptor Lambda"""
    mcp = event.get("mcp", {})
    resp = mcp.get("gatewayResponse", {})
    req = mcp.get("gatewayRequest", {})

    # [重要] Authorizationヘッダーは gatewayRequest から取得する
    req_headers = req.get("headers", {})
    body = resp.get("body") or {}

    # ケースインセンシティブな Authorization ヘッダー取得
    auth = None
    for key, value in req_headers.items():
        if key.lower() == "authorization":
            auth = value
            break

    result = body.get("result", {})

    # tools/list または structuredContent からツール一覧を取得
    tools = result.get("tools", []) or result.get("structuredContent", {}).get(
        "tools", []
    )

    if not tools:
        # ツールリストでない場合はそのまま通過
        return {
            "interceptorOutputVersion": "1.0",
            "mcp": {
                "transformedGatewayResponse": {
                    "headers": resp.get("headers", {}),
                    "body": body,
                }
            },
        }

    try:
        token = (
            auth.replace("Bearer ", "")
            if auth and auth.startswith("Bearer ")
            else ""
        )
        if not token:
            raise ValueError("No Bearer token found")

        claims = decode_jwt_payload(token)
        role = claims.get("role", "guest")
        filtered = filter_tools(tools, role)

        # JSON-RPC準拠のレスポンスを構築
        filtered_body = {
            "jsonrpc": body.get("jsonrpc", "2.0"),
            "result": {"tools": filtered},
            "id": body.get("id"),
        }

    except Exception as e:
        logger.warning(f"JWT validation failed: {e}")
        # fail-closed: JSON-RPC準拠の空ツールリスト
        filtered_body = {
            "jsonrpc": "2.0",
            "result": {"tools": []},
            "id": body.get("id"),
        }

    return {
        "interceptorOutputVersion": "1.0",
        "mcp": {
            "transformedGatewayResponse": {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": filtered_body,
            }
        },
    }
