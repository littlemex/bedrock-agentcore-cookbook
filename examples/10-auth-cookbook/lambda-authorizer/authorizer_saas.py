"""
Lambda Authorizer for SaaS Multi-Tenant (Chapter 12)

SaaSマルチテナント環境用のLambda Authorizer
- JWT署名検証
- DynamoDBからテナント情報を取得
- テナントアクティブ状態の確認
- fail-closed設計
"""

import json
import logging
import os

import boto3
import jwt

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 環境変数
JWKS_URL = os.environ["JWKS_URL"]
CLIENT_ID = os.environ["CLIENT_ID"]
TENANT_TABLE = os.environ["TENANT_TABLE"]

# グローバルスコープで初期化
jwks_client = jwt.PyJWKClient(JWKS_URL)
dynamodb = boto3.resource("dynamodb")
tenant_table = dynamodb.Table(TENANT_TABLE)


def lambda_handler(event, context):
    """HTTP API V2 Lambda Authorizer -- SaaSテナント認証"""
    try:
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
            options={"require": ["exp", "client_id", "token_use"]},
            audience=CLIENT_ID,
        )

        # 必須クレームの検証
        tenant_id = claims.get("tenant_id")
        if not tenant_id:
            return build_deny_response("Missing tenant_id claim")

        user_id = claims.get("sub")
        role = claims.get("role", "user")

        # DynamoDBからテナント情報を取得
        tenant_info = get_tenant_info(tenant_id)
        if not tenant_info:
            return build_deny_response("Tenant not found")

        # [CRITICAL] テナントのアクティブ状態を確認
        if tenant_info.get("status") != "active":
            logger.warning(f"Inactive tenant access attempt: {tenant_id}")
            return build_deny_response("Tenant is not active")

        # HTTP API V2形式のレスポンス
        return {
            "isAuthorized": True,
            "context": {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "role": role,
                "plan": tenant_info.get("plan", "standard"),
                "allowed_agents": json.dumps(
                    tenant_info.get("allowed_agents", [])
                ),
            },
        }

    except jwt.ExpiredSignatureError:
        logger.error("JWT has expired")
        return build_deny_response("Token expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"JWT validation failed: {e}")
        return build_deny_response("Invalid token")
    except Exception as e:
        logger.error(f"Authorization failed: {str(e)}")
        return build_deny_response("Authorization failed")


def get_tenant_info(tenant_id):
    """DynamoDBからテナント情報を取得する"""
    try:
        response = tenant_table.get_item(
            Key={"PK": f"TENANT#{tenant_id}", "SK": "METADATA"}
        )
        return response.get("Item")
    except Exception as e:
        logger.error(f"DynamoDB query failed: {e}")
        return None


def build_deny_response(reason):
    """認可拒否レスポンス（内部情報は含めない）"""
    logger.warning(f"Authorization denied: {reason}")
    return {
        "isAuthorized": False,
        "context": {"error": "Access denied"},
    }
