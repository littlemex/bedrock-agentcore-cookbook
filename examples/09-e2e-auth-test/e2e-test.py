#!/usr/bin/env python3
"""
AgentCore Authentication & Authorization E2E Test
"""
import json
import os
import sys
import base64
import hmac
import hashlib
from datetime import datetime
import boto3
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

AWS_REGION = os.getenv("AWS_REGION")
USER_POOL_ID = os.getenv("USER_POOL_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
PROJECT_PREFIX = os.getenv("PROJECT_PREFIX")
TENANT_TABLE = os.getenv("TENANT_TABLE")
SHARING_TABLE = os.getenv("SHARING_TABLE")

# AWS clients
cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

# Test results
test_results = []


def log_test(name, passed, details=""):
    """テスト結果を記録"""
    status = "[PASS]" if passed else "[FAIL]"
    print(f"{status} {name}")
    if details:
        print(f"       {details}")
    test_results.append({"name": name, "passed": passed, "details": details})


def get_secret_hash(username, client_id, client_secret):
    """Cognito Secret Hash を計算"""
    message = bytes(username + client_id, "utf-8")
    secret = bytes(client_secret, "utf-8")
    dig = hmac.new(secret, msg=message, digestmod=hashlib.sha256).digest()
    return base64.b64encode(dig).decode()


def create_test_user(email, password, tenant_id):
    """テストユーザーを作成"""
    try:
        # ユーザー作成
        cognito_client.admin_create_user(
            UserPoolId=USER_POOL_ID,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "custom:tenant_id", "Value": tenant_id},
            ],
            MessageAction="SUPPRESS",
        )

        # パスワード設定
        cognito_client.admin_set_user_password(
            UserPoolId=USER_POOL_ID,
            Username=email,
            Password=password,
            Permanent=True,
        )

        return True
    except cognito_client.exceptions.UsernameExistsException:
        # ユーザーが既に存在する場合はOK
        return True
    except Exception as e:
        print(f"[ERROR] Failed to create user {email}: {e}")
        return False


def get_jwt_token(username, password):
    """JWT トークンを取得"""
    try:
        # Client Secret を取得
        client_response = cognito_client.describe_user_pool_client(
            UserPoolId=USER_POOL_ID,
            ClientId=CLIENT_ID,
        )
        client_secret = client_response["UserPoolClient"].get("ClientSecret")

        auth_params = {
            "USERNAME": username,
            "PASSWORD": password,
        }

        if client_secret:
            secret_hash = get_secret_hash(username, CLIENT_ID, client_secret)
            auth_params["SECRET_HASH"] = secret_hash

        response = cognito_client.admin_initiate_auth(
            UserPoolId=USER_POOL_ID,
            ClientId=CLIENT_ID,
            AuthFlow="ADMIN_NO_SRP_AUTH",
            AuthParameters=auth_params,
        )

        return response["AuthenticationResult"]["IdToken"]
    except Exception as e:
        print(f"[ERROR] Failed to get JWT token for {username}: {e}")
        return None


def test_lambda_authorizer(function_name, token, expected_authorized):
    """Lambda Authorizer をテスト"""
    event = {
        "headers": {
            "authorization": f"Bearer {token}"
        },
        "requestContext": {
            "http": {
                "method": "POST",
                "path": "/agents/invoke"
            }
        }
    }

    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(event),
        )

        result = json.loads(response["Payload"].read())
        is_authorized = result.get("isAuthorized", False)

        passed = is_authorized == expected_authorized
        details = f"Expected: {expected_authorized}, Got: {is_authorized}"

        return passed, details
    except Exception as e:
        return False, f"Exception: {str(e)}"


def test_request_interceptor(function_name, token, action, expected_allowed):
    """Request Interceptor をテスト"""
    event = {
        "headers": {
            "authorization": f"Bearer {token}"
        },
        "body": json.dumps({
            "action": action,
            "resource": "test-resource"
        })
    }

    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(event),
        )

        result = json.loads(response["Payload"].read())

        # エラーが返ってきた場合は拒否されたと判断
        if "errorMessage" in result or "statusCode" in result and result["statusCode"] >= 400:
            is_allowed = False
        else:
            is_allowed = True

        passed = is_allowed == expected_allowed
        details = f"Expected allowed: {expected_allowed}, Got: {is_allowed}"

        return passed, details
    except Exception as e:
        return False, f"Exception: {str(e)}"


def test_response_interceptor(function_name, token, role):
    """Response Interceptor をテスト"""
    # tools/list レスポンスをモック
    event = {
        "headers": {
            "authorization": f"Bearer {token}"
        },
        "body": json.dumps({
            "tools": [
                {"name": "search_memory", "description": "Search memory"},
                {"name": "store_memory", "description": "Store memory"},
                {"name": "delete_memory", "description": "Delete memory"},
            ]
        })
    }

    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(event),
        )

        result = json.loads(response["Payload"].read())

        if "body" in result:
            body = json.loads(result["body"])
            tools = body.get("tools", [])
        else:
            tools = result.get("tools", [])

        # admin はすべてのツールにアクセス可能
        if role == "admin":
            expected_count = 3
        # user は search_memory のみ
        elif role == "user":
            expected_count = 1
        else:
            expected_count = 0

        passed = len(tools) == expected_count
        details = f"Expected {expected_count} tools, Got {len(tools)}"

        return passed, details
    except Exception as e:
        return False, f"Exception: {str(e)}"


def test_private_sharing():
    """Private Sharing をテスト"""
    # DynamoDB から共有設定を取得
    table = dynamodb.Table(SHARING_TABLE)

    try:
        response = table.get_item(
            Key={
                "resource_id": "resource-001",
                "consumer_tenant_id": "tenant-b"
            }
        )

        if "Item" in response:
            item = response["Item"]
            passed = (
                item["owner_tenant_id"] == "tenant-a" and
                item["sharing_mode"] == "private"
            )
            details = f"Sharing record found: {item}"
        else:
            passed = False
            details = "No sharing record found"

        return passed, details
    except Exception as e:
        return False, f"Exception: {str(e)}"


def main():
    """メインテスト実行"""
    print("=" * 60)
    print("AgentCore Authentication & Authorization E2E Test")
    print("=" * 60)
    print(f"Region: {AWS_REGION}")
    print(f"User Pool: {USER_POOL_ID}")
    print(f"Project: {PROJECT_PREFIX}")
    print("=" * 60)
    print()

    # Phase 1: セットアップ
    print("[PHASE 1] Setup Test Users")
    print("-" * 60)

    test_users = [
        ("admin@tenant-a.example.com", "TestPass123!", "tenant-a"),
        ("user@tenant-a.example.com", "TestPass123!", "tenant-a"),
        ("user@tenant-b.example.com", "TestPass123!", "tenant-b"),
    ]

    for email, password, tenant_id in test_users:
        success = create_test_user(email, password, tenant_id)
        log_test(f"Create user: {email}", success)

    print()

    # Phase 2: JWT トークン取得
    print("[PHASE 2] Get JWT Tokens")
    print("-" * 60)

    tokens = {}
    for email, password, tenant_id in test_users:
        token = get_jwt_token(email, password)
        if token:
            tokens[email] = token
            log_test(f"Get JWT token: {email}", True)
        else:
            log_test(f"Get JWT token: {email}", False, "Failed to get token")

    print()

    # Phase 3: Lambda Authorizer テスト
    print("[PHASE 3] Test Lambda Authorizer")
    print("-" * 60)

    authorizer_function = f"{PROJECT_PREFIX}-authorizer-basic"

    # 有効なトークンは認証成功
    for email in tokens:
        passed, details = test_lambda_authorizer(
            authorizer_function,
            tokens[email],
            expected_authorized=True
        )
        log_test(f"Authorizer: {email} (valid token)", passed, details)

    # 無効なトークンは認証失敗
    passed, details = test_lambda_authorizer(
        authorizer_function,
        "invalid-token",
        expected_authorized=False
    )
    log_test("Authorizer: invalid token", passed, details)

    print()

    # Phase 4: Request Interceptor テスト
    print("[PHASE 4] Test Request Interceptor")
    print("-" * 60)

    interceptor_function = f"{PROJECT_PREFIX}-request-interceptor-basic"

    # MCP ライフサイクルメソッドはバイパス
    # tools/call は認証必要

    # admin@tenant-a: すべてのアクション許可
    if "admin@tenant-a.example.com" in tokens:
        passed, details = test_request_interceptor(
            interceptor_function,
            tokens["admin@tenant-a.example.com"],
            "mcp-target___search_memory",
            expected_allowed=True
        )
        log_test("Request Interceptor: admin can search_memory", passed, details)

    # user@tenant-a: search_memory のみ許可
    if "user@tenant-a.example.com" in tokens:
        passed, details = test_request_interceptor(
            interceptor_function,
            tokens["user@tenant-a.example.com"],
            "mcp-target___search_memory",
            expected_allowed=True
        )
        log_test("Request Interceptor: user can search_memory", passed, details)

    print()

    # Phase 5: Response Interceptor テスト
    print("[PHASE 5] Test Response Interceptor")
    print("-" * 60)

    response_function = f"{PROJECT_PREFIX}-response-interceptor-basic"

    # admin: すべてのツール
    if "admin@tenant-a.example.com" in tokens:
        passed, details = test_response_interceptor(
            response_function,
            tokens["admin@tenant-a.example.com"],
            "admin"
        )
        log_test("Response Interceptor: admin sees all tools", passed, details)

    # user: 制限されたツール
    if "user@tenant-a.example.com" in tokens:
        passed, details = test_response_interceptor(
            response_function,
            tokens["user@tenant-a.example.com"],
            "user"
        )
        log_test("Response Interceptor: user sees limited tools", passed, details)

    print()

    # Phase 6: Private Sharing テスト
    print("[PHASE 6] Test Private Sharing")
    print("-" * 60)

    passed, details = test_private_sharing()
    log_test("Private Sharing: tenant-a shares resource-001 to tenant-b", passed, details)

    print()

    # サマリー
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)

    total = len(test_results)
    passed = sum(1 for r in test_results if r["passed"])
    failed = total - passed

    print(f"Total:  {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed > 0:
        print()
        print("Failed tests:")
        for result in test_results:
            if not result["passed"]:
                print(f"  - {result['name']}")
                if result["details"]:
                    print(f"    {result['details']}")

    print("=" * 60)

    # 終了コード
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
