"""
Request Interceptor for AgentCore Gateway (Chapter 6)

Request Interceptorは以下を実施します:
- MCPライフサイクルメソッドのバイパス
- システムツールの自動許可
- JWT検証（Defense in Depth）
- ツール呼び出し権限の検査
"""

import base64
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

# MCPライフサイクルメソッド -- 認可処理をバイパス
MCP_LIFECYCLE_METHODS = {
    "initialize",
    "notifications/initialized",
    "ping",
    "tools/list",
}

# AgentCoreシステムツール -- 認可不要
SYSTEM_TOOLS = {"x_amz_bedrock_agentcore_search"}

# ロール別のツール呼び出し権限
ROLE_TOOL_PERMISSIONS = {
    "admin": ["*"],
    "user": ["retrieve_doc", "search_memory"],
    "guest": [],
}


def extract_claims_from_jwt(token):
    """JWT トークンから claims を抽出し、署名を検証する"""
    try:
        if token.startswith("Bearer "):
            token = token[7:]

        if jwks_client:
            # 本番環境: PyJWT + JWKS署名検証
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            # IdToken を受け入れる (aud クレームで検証)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=CLIENT_ID,  # IdToken の aud を検証
                options={"require": ["exp", "aud", "token_use"]},
            )
            return claims
        else:
            # 開発環境のみ: base64デコード（署名検証なし）
            # 本番環境では絶対に使用しないこと
            logger.warning(
                "JWKS_URL not set - using insecure base64 decode"
            )
            parts = token.split(".")
            if len(parts) != 3:
                return None
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            decoded = base64.urlsafe_b64decode(payload)
            return json.loads(decoded)
    except Exception as e:
        logger.warning("Failed to extract claims: %s", e)
        return None


def is_tool_allowed(tool_name, role):
    """ツール呼び出しが許可されているか確認する"""
    allowed = ROLE_TOOL_PERMISSIONS.get(role, [])
    if not allowed:
        return False
    if "*" in allowed:
        return True
    return tool_name in allowed


def _allow_request(headers, body):
    """リクエストを通過させる"""
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
    """リクエストを拒否する (MCP JSON-RPC 準拠)"""
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
                        "content": [{"type": "text", "text": message}],
                    },
                },
            }
        },
    }


def lambda_handler(event, context):
    try:
        mcp_data = event.get("mcp", {})
        gateway_request = mcp_data.get("gatewayRequest", {})
        headers = gateway_request.get("headers", {})
        body = gateway_request.get("body", {})

        if isinstance(body, str):
            body = json.loads(body)

        method = body.get("method", "")
        rpc_id = body.get("id")

        # 1. MCPライフサイクルメソッドのバイパス
        if method in MCP_LIFECYCLE_METHODS:
            return _allow_request(headers, body)

        # 2. Authorizationヘッダーの取得（ケースインセンシティブ）
        auth_header = None
        for key, value in headers.items():
            if key.lower() == "authorization":
                auth_header = value
                break

        if not auth_header:
            return _deny_request(rpc_id, "Authorization required")

        # 3. JWTからclaimsを取得
        claims = extract_claims_from_jwt(auth_header)
        if not claims:
            return _deny_request(rpc_id, "Invalid authorization token")

        role = claims.get("role", "guest")
        tenant_id = claims.get("tenant_id", "")
        user_id = claims.get("sub", "")

        # 4. tools/callの場合はツール呼び出し権限を検査
        if method == "tools/call":
            params = body.get("params", {})
            tool_name = params.get("name", "")
            actual_tool_name = (
                tool_name.split("___")[-1] if "___" in tool_name else tool_name
            )

            # システムツールはバイパス
            if actual_tool_name in SYSTEM_TOOLS:
                return _allow_request(headers, body)

            # テナント境界チェック（namespaceパラメータ）
            arguments = params.get("arguments", {})
            namespace = arguments.get("namespace", "")
            if namespace and namespace != tenant_id:
                return _deny_request(
                    rpc_id,
                    f"Access denied: cross-tenant access not allowed "
                    f"(user tenant: '{tenant_id}', requested namespace: '{namespace}')",
                )

            # ロールベースのツール呼び出し権限チェック
            if not is_tool_allowed(actual_tool_name, role):
                return _deny_request(
                    rpc_id,
                    f"Access denied: tool '{actual_tool_name}' "
                    f"is not allowed for role '{role}'",
                )

        return _allow_request(headers, body)

    except Exception as e:
        logger.error("Request Interceptor error: %s", e)
        return _deny_request(None, "Authorization failed")
