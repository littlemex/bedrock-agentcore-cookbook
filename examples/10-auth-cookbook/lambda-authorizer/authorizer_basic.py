"""
Lambda Authorizer for AgentCore Gateway (Basic)

Chapter 4: Lambda Authorizer -- JWT署名検証とテナント認証

このAuthorizerは以下を実施します:
- JWT署名検証（PyJWT + JWKS）
- テナントID検証
- ロール検証
- fail-closed設計
"""

import json
import logging
import os

import jwt

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 環境変数
JWKS_URL = os.environ["JWKS_URL"]
CLIENT_ID = os.environ["CLIENT_ID"]

# グローバルスコープでJWKSクライアントを初期化（ウォームスタート時にキャッシュ再利用）
jwks_client = jwt.PyJWKClient(JWKS_URL)


def lambda_handler(event, context):
    """HTTP API V2 Lambda Authorizer"""
    try:
        # Authorizationヘッダーの取得
        headers = event.get("headers", {})
        auth_header = headers.get("authorization", "")

        if not auth_header.startswith("Bearer "):
            return build_deny_response("Missing Bearer token")

        token = auth_header[7:]

        # JWT署名検証
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=CLIENT_ID,  # ID Token の aud を検証
            options={
                "require": ["exp", "sub", "aud", "token_use"],
            },
        )

        # token_use 検証 (ID Token を期待)
        if claims.get("token_use") != "id":
            return build_deny_response("Invalid token_use")

        tenant_id = claims.get("tenant_id")
        if not tenant_id:
            return build_deny_response("Missing tenant_id claim")

        user_id = claims.get("sub")
        role = claims.get("role", "guest")

        # HTTP API V2形式のレスポンス
        return {
            "isAuthorized": True,
            "context": {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "role": role,
            },
        }

    except jwt.ExpiredSignatureError:
        logger.error("JWT has expired")
        return build_deny_response("Token expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"JWT validation failed: {e}")
        return build_deny_response("Invalid token")
    except Exception as e:
        logger.error(f"Authorization failed: {e}")
        return build_deny_response("Authorization failed")


def build_deny_response(reason):
    """認可拒否レスポンス（内部情報は含めない）"""
    logger.warning(f"Authorization denied: {reason}")
    return {
        "isAuthorized": False,
        "context": {"error": "Access denied"},
    }
