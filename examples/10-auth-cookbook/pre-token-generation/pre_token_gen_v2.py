"""
Cognito Pre Token Generation Lambda V2 (Chapter 10)

マルチエージェント環境用のPre Token Generation Lambda
- DynamoDBからユーザー情報を取得
- agent_idのサーバーサイド検証
- カスタムクレーム（role, groups, agent_id）の注入
"""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 環境変数
AUTH_POLICY_TABLE = os.environ.get("AUTH_POLICY_TABLE", "")

# グローバルスコープで初期化
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(AUTH_POLICY_TABLE) if AUTH_POLICY_TABLE else None


def lambda_handler(event, context):
    """Cognito Pre Token Generation Lambda V2"""
    email = event["request"]["userAttributes"].get("email", "")

    # [SECURITY] DynamoDBから取得したユーザー情報を信頼する
    # clientMetadataからのagent_idは検証用としてのみ使用
    requested_agent_id = (
        event["request"].get("clientMetadata", {}).get("agent_id", "")
    )

    user_info = lookup_user_by_email(email)
    if not user_info:
        user_info = {"role": "guest", "groups": [], "allowed_agents": []}

    claims_to_add = {
        "role": user_info["role"],
        "groups": json.dumps(user_info.get("groups", [])),
    }

    # [SECURITY] サーバーサイドでagent_idを検証
    allowed_agents = user_info.get("allowed_agents", [])

    if requested_agent_id and requested_agent_id in allowed_agents:
        claims_to_add["agent_id"] = requested_agent_id
    elif len(allowed_agents) == 1:
        claims_to_add["agent_id"] = allowed_agents[0]
    # それ以外の場合はagent_idクレームを付与しない（Cedarで拒否される）

    # V2形式のレスポンス
    event["response"] = {
        "claimsAndScopeOverrideDetails": {
            "accessTokenGeneration": {
                "claimsToAddOrOverride": claims_to_add,
            }
        }
    }
    return event


def lookup_user_by_email(email):
    """AuthPolicyTableからemailでユーザーを検索"""
    if not table:
        logger.error("AUTH_POLICY_TABLE not configured")
        return None

    try:
        response = table.query(
            IndexName="GSI-Email",
            KeyConditionExpression="email = :email",
            ExpressionAttributeValues={":email": email},
            Limit=1,
        )
        items = response.get("Items", [])
        return items[0] if items else None
    except Exception as e:
        logger.error(f"DynamoDB query failed: {e}")
        return None
