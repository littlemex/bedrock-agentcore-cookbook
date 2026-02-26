"""
Request Interceptor for Private Sharing (Chapter 13)

Private Sharingの共有先検証をRequest Interceptorで実施します:
- DynamoDB Sharingテーブルを参照
- 共有先テナントの場合のみ許可
- キャッシュ戦略対応（Lambdaグローバル変数）
"""

import base64
import json
import logging
import os
import time

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 環境変数
SHARING_TABLE = os.environ.get("SHARING_TABLE", "")

# グローバルスコープで初期化
dynamodb = boto3.resource("dynamodb")
sharing_table = dynamodb.Table(SHARING_TABLE) if SHARING_TABLE else None

# キャッシュ（Lambdaグローバル変数）
sharing_cache = {}
CACHE_TTL = 60  # 60秒


def decode_jwt_payload(token):
    """JWT ペイロードを Base64 デコードする

    注意: 本番環境では必ずPyJWT + JWKSによる署名検証を実施すること
    """
    try:
        if token.startswith("Bearer "):
            token = token[7:]
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
        logger.warning(f"Failed to decode JWT: {e}")
        return None


def check_private_sharing(resource_id, consumer_tenant_id):
    """DynamoDB Sharingテーブルで共有先テナントを検証する"""
    if not sharing_table:
        logger.error("SHARING_TABLE not configured")
        return False

    try:
        response = sharing_table.get_item(
            Key={
                "PK": f"RESOURCE#{resource_id}",
                "SK": f"SHARED_TO#{consumer_tenant_id}",
            }
        )
        item = response.get("Item")
        if item and item.get("status") == "active":
            return True
        return False
    except Exception as e:
        logger.error(f"DynamoDB query failed: {e}")
        return False


def check_private_sharing_with_cache(resource_id, consumer_tenant_id):
    """キャッシュ付きの共有先検証"""
    cache_key = f"{resource_id}:{consumer_tenant_id}"
    current_time = time.time()

    # キャッシュヒット & TTL有効
    cached = sharing_cache.get(cache_key)
    if cached and current_time - cached["timestamp"] < CACHE_TTL:
        logger.info(f"[CACHE HIT] {cache_key}")
        return cached["result"]

    # キャッシュミス: DynamoDBを参照
    result = check_private_sharing(resource_id, consumer_tenant_id)
    sharing_cache[cache_key] = {"result": result, "timestamp": current_time}
    logger.info(f"[CACHE MISS] {cache_key}")
    return result


def extract_resource_id(event):
    """イベントからリソースIDを抽出する

    実装はユースケースに応じて調整が必要
    """
    # 例: AgentCore Gatewayのメタデータから取得
    # 実際の実装では、リクエストのパスやパラメータから取得
    gateway_request = event.get("mcp", {}).get("gatewayRequest", {})
    # TODO: 実際のリソースID抽出ロジックを実装
    return "agent-id-example"


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
    logger.warning(f"Denying request: {message}")
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
    """Private Sharing用Request Interceptor"""
    try:
        mcp_data = event.get("mcp", {})
        gateway_request = mcp_data.get("gatewayRequest", {})
        headers = gateway_request.get("headers", {})
        body = gateway_request.get("body", {})

        if isinstance(body, str):
            body = json.loads(body)

        rpc_id = body.get("id")

        # Authorizationヘッダーの取得（ケースインセンシティブ）
        auth_header = None
        for key, value in headers.items():
            if key.lower() == "authorization":
                auth_header = value
                break

        if not auth_header:
            return _deny_request(rpc_id, "Authorization required")

        # JWTからテナントIDを取得
        claims = decode_jwt_payload(auth_header)
        if not claims:
            return _deny_request(rpc_id, "Invalid authorization token")

        consumer_tenant_id = claims.get("tenant_id", "")
        if not consumer_tenant_id:
            return _deny_request(rpc_id, "Missing tenant_id")

        # リソースIDを取得
        target_id = extract_resource_id(event)

        # Private Sharing検証
        # E2E検証結果: Gateway処理順序は Interceptor -> Cedar のため、
        # Interceptorで全リソース（所有者、Public、Private）を検証し、
        # その後Cedarがpermitポリシーに基づいて最終評価を行う
        if check_private_sharing_with_cache(target_id, consumer_tenant_id):
            logger.info(
                f"Private sharing allowed: {target_id} -> {consumer_tenant_id}"
            )
            return _allow_request(headers, body)
        else:
            return _deny_request(
                rpc_id,
                f"Access denied: resource '{target_id}' "
                f"is not shared with tenant '{consumer_tenant_id}'",
            )

    except Exception as e:
        logger.error(f"Request Interceptor error: {e}")
        return _deny_request(None, "Authorization failed")
