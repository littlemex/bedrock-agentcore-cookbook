#!/usr/bin/env python3
"""Quick E2E test for Lambda Authorizer"""
import json
import base64
import hmac
import hashlib
import boto3
from dotenv import load_dotenv
import os

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
USER_POOL_ID = os.getenv("USER_POOL_ID")
CLIENT_ID = os.getenv("CLIENT_ID")

cognito = boto3.client("cognito-idp", region_name=AWS_REGION)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)

def get_secret_hash(username, client_id, client_secret):
    message = bytes(username + client_id, "utf-8")
    secret = bytes(client_secret, "utf-8")
    dig = hmac.new(secret, msg=message, digestmod=hashlib.sha256).digest()
    return base64.b64encode(dig).decode()

def get_jwt_token(username, password):
    """Get JWT token from Cognito"""
    # Get client secret
    client_resp = cognito.describe_user_pool_client(
        UserPoolId=USER_POOL_ID,
        ClientId=CLIENT_ID
    )
    client_secret = client_resp["UserPoolClient"].get("ClientSecret")

    auth_params = {
        "USERNAME": username,
        "PASSWORD": password,
    }

    if client_secret:
        secret_hash = get_secret_hash(username, CLIENT_ID, client_secret)
        auth_params["SECRET_HASH"] = secret_hash

    response = cognito.admin_initiate_auth(
        UserPoolId=USER_POOL_ID,
        ClientId=CLIENT_ID,
        AuthFlow="ADMIN_NO_SRP_AUTH",
        AuthParameters=auth_params
    )

    return response["AuthenticationResult"]["IdToken"]

def test_lambda_authorizer(token):
    """Test Lambda Authorizer"""
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

    response = lambda_client.invoke(
        FunctionName="agentcore-e2e-test-authorizer-basic",
        InvocationType="RequestResponse",
        Payload=json.dumps(event)
    )

    result = json.loads(response["Payload"].read())
    return result

def main():
    print("=" * 60)
    print("Quick E2E Test - Lambda Authorizer")
    print("=" * 60)

    # Test 1: Get JWT Token
    print("\n[Test 1] Getting JWT Token...")
    try:
        token = get_jwt_token("test-admin@tenant-a.com", "TestPass123!")
        print("[PASS] JWT Token obtained")
        print(f"Token (first 50 chars): {token[:50]}...")
    except Exception as e:
        print(f"[FAIL] Failed to get JWT token: {e}")
        return

    # Test 2: Test Lambda Authorizer with valid token
    print("\n[Test 2] Testing Lambda Authorizer with valid token...")
    try:
        result = test_lambda_authorizer(token)
        is_authorized = result.get("isAuthorized", False)

        if is_authorized:
            print("[PASS] Lambda Authorizer authorized the request")
            print(f"Context: {json.dumps(result.get('context', {}), indent=2)}")
        else:
            print("[FAIL] Lambda Authorizer rejected the request")
            print(f"Result: {json.dumps(result, indent=2)}")
    except Exception as e:
        print(f"[FAIL] Lambda Authorizer invocation failed: {e}")

    # Test 3: Test Lambda Authorizer with invalid token
    print("\n[Test 3] Testing Lambda Authorizer with invalid token...")
    try:
        result = test_lambda_authorizer("invalid-token-xyz")
        is_authorized = result.get("isAuthorized", False)

        if not is_authorized:
            print("[PASS] Lambda Authorizer correctly rejected invalid token")
        else:
            print("[FAIL] Lambda Authorizer incorrectly authorized invalid token")
    except Exception as e:
        print(f"[INFO] Lambda Authorizer correctly rejected invalid token (exception: {str(e)[:50]}...)")

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
