#!/usr/bin/env python3
"""
Test Inbound Auth Integration Flow

Tests the integration of:
- L1: Lambda Authorizer (JWT verification, tenant_id extraction)
- L3: Request Interceptor (tenant boundary checks)
- L2: Cedar Policy (tool authorization) - if Gateway is deployed

This test validates the Inbound Auth flow described in Chapter 1.
"""

import boto3
import json
import os
import sys
import hmac
import hashlib
import base64
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestInboundAuth:
    def __init__(self):
        self.region = os.getenv('AWS_REGION', 'us-east-1')
        self.lambda_client = boto3.client('lambda', region_name=self.region)
        self.cognito_client = boto3.client('cognito-idp', region_name=self.region)

        # Load configuration from .env
        self.user_pool_id = os.getenv('USER_POOL_ID')
        self.client_id = os.getenv('CLIENT_ID')
        self.client_secret = os.getenv('CLIENT_SECRET')
        self.authorizer_function_name = os.getenv('AUTHORIZER_FUNCTION_NAME', 'agentcore-e2e-test-authorizer-basic')
        self.interceptor_function_name = os.getenv('INTERCEPTOR_FUNCTION_NAME', 'agentcore-e2e-test-request-interceptor-basic')

        # Test users
        self.test_users = {
            'admin_tenant_a': {
                'email': 'admin@tenant-a.example.com',
                'password': 'TempPass123!',
                'tenant_id': 'tenant-a',
                'role': 'admin'
            },
            'user_tenant_a': {
                'email': 'user@tenant-a.example.com',
                'password': 'TempPass123!',
                'tenant_id': 'tenant-a',
                'role': 'user'
            },
            'user_tenant_b': {
                'email': 'user@tenant-b.example.com',
                'password': 'TempPass123!',
                'tenant_id': 'tenant-b',
                'role': 'user'
            }
        }

    def calculate_secret_hash(self, username):
        """
        Calculate SECRET_HASH for Cognito authentication.

        SECRET_HASH = Base64(HMAC_SHA256(client_secret, username + client_id))
        """
        if not self.client_secret:
            return None

        message = username + self.client_id
        dig = hmac.new(
            self.client_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
        return base64.b64encode(dig).decode()

    def get_jwt_token(self, username, password):
        """
        Get JWT token from Cognito using USER_PASSWORD_AUTH flow.

        Note: This requires ALLOW_USER_PASSWORD_AUTH to be enabled in Cognito App Client.
        """
        try:
            auth_params = {
                'USERNAME': username,
                'PASSWORD': password
            }

            # Add SECRET_HASH if client secret is configured
            secret_hash = self.calculate_secret_hash(username)
            if secret_hash:
                auth_params['SECRET_HASH'] = secret_hash

            response = self.cognito_client.initiate_auth(
                ClientId=self.client_id,
                AuthFlow='USER_PASSWORD_AUTH',
                AuthParameters=auth_params
            )
            # Use IdToken (not AccessToken) for Lambda Authorizer
            # IdToken contains custom claims (tenant_id, role) added by Pre Token Generation Lambda
            # AccessToken does not support custom claims from Pre Token Generation
            return response['AuthenticationResult']['IdToken']
        except Exception as e:
            print(f"[ERROR] Failed to get JWT token for {username}: {e}")
            return None

    def invoke_lambda_authorizer(self, jwt_token):
        """
        Invoke Lambda Authorizer with JWT token.

        Returns the Lambda Authorizer response with isAuthorized and context.
        """
        event = {
            'type': 'REQUEST',
            'methodArn': 'arn:aws:execute-api:us-east-1:123456789012:abcdef/*/GET/test',
            'headers': {
                'authorization': f'Bearer {jwt_token}'
            }
        }

        try:
            response = self.lambda_client.invoke(
                FunctionName=self.authorizer_function_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(event)
            )

            payload = json.loads(response['Payload'].read())
            return payload
        except Exception as e:
            print(f"[ERROR] Failed to invoke Lambda Authorizer: {e}")
            return None

    def invoke_request_interceptor(self, mcp_request, context, jwt_token):
        """
        Invoke Request Interceptor with MCP request, context, and JWT token.

        Returns the transformed MCP request.
        """
        event = {
            'mcp': {
                'gatewayRequest': {
                    'headers': {
                        'authorization': f'Bearer {jwt_token}'
                    },
                    'body': mcp_request,
                    'context': context
                }
            }
        }

        try:
            response = self.lambda_client.invoke(
                FunctionName=self.interceptor_function_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(event)
            )

            payload = json.loads(response['Payload'].read())
            return payload
        except Exception as e:
            print(f"[ERROR] Failed to invoke Request Interceptor: {e}")
            return None

    def test_01_lambda_authorizer_jwt_verification(self):
        """
        Test IN-01: Lambda Authorizer による JWT 署名検証
        """
        print("\n[TEST IN-01] Lambda Authorizer JWT Verification")
        print("=" * 60)

        # Test with valid JWT
        print("\n[1] Test with valid JWT (admin@tenant-a)")
        user = self.test_users['admin_tenant_a']
        jwt_token = self.get_jwt_token(user['email'], user['password'])

        if not jwt_token:
            print("[SKIP] Cannot obtain JWT token. Check Cognito Auth Flow settings.")
            return False

        response = self.invoke_lambda_authorizer(jwt_token)

        if response and response.get('isAuthorized') == True:
            print(f"[PASS] Lambda Authorizer returned isAuthorized: true")
            print(f"[INFO] Context: {json.dumps(response.get('context', {}), indent=2)}")
            return True
        else:
            print(f"[FAIL] Lambda Authorizer returned: {response}")
            return False

    def test_02_tenant_id_extraction(self):
        """
        Test IN-02: tenant_id の抽出と context への追加
        """
        print("\n[TEST IN-02] Tenant ID Extraction and Context")
        print("=" * 60)

        for user_key, user_data in self.test_users.items():
            print(f"\n[Testing user: {user_data['email']}]")

            jwt_token = self.get_jwt_token(user_data['email'], user_data['password'])
            if not jwt_token:
                print(f"[SKIP] Cannot obtain JWT token for {user_data['email']}")
                continue

            response = self.invoke_lambda_authorizer(jwt_token)

            if not response or not response.get('isAuthorized'):
                print(f"[FAIL] Authorization failed for {user_data['email']}")
                continue

            context = response.get('context', {})
            extracted_tenant_id = context.get('tenant_id')
            expected_tenant_id = user_data['tenant_id']

            if extracted_tenant_id == expected_tenant_id:
                print(f"[PASS] tenant_id extracted correctly: {extracted_tenant_id}")
            else:
                print(f"[FAIL] Expected tenant_id: {expected_tenant_id}, Got: {extracted_tenant_id}")
                return False

        return True

    def test_03_request_interceptor_tenant_boundary(self):
        """
        Test IN-03: Request Interceptor によるテナント境界チェック
        """
        print("\n[TEST IN-03] Request Interceptor Tenant Boundary Check")
        print("=" * 60)

        # Get JWT and context for tenant-a admin
        user = self.test_users['admin_tenant_a']
        jwt_token = self.get_jwt_token(user['email'], user['password'])

        if not jwt_token:
            print("[SKIP] Cannot obtain JWT token")
            return False

        auth_response = self.invoke_lambda_authorizer(jwt_token)
        if not auth_response or not auth_response.get('isAuthorized'):
            print("[FAIL] Authorization failed")
            return False

        context = auth_response.get('context', {})

        # Test 1: Access within tenant boundary (should pass)
        print("\n[1] Test access within tenant boundary (tenant-a -> tenant-a resource)")
        mcp_request = {
            'method': 'tools/call',
            'params': {
                'name': 'search_memory',
                'arguments': {
                    'namespace': 'tenant-a',
                    'query': 'test'
                }
            }
        }

        result = self.invoke_request_interceptor(mcp_request, context, jwt_token)
        # Check if request was allowed (not denied)
        if result and result.get('mcp', {}).get('transformedGatewayRequest'):
            print("[PASS] Request within tenant boundary passed")
        else:
            print(f"[FAIL] Request within tenant boundary failed: {result}")
            return False

        # Test 2: Cross-tenant access (should be rejected)
        print("\n[2] Test cross-tenant access (tenant-a -> tenant-b resource)")
        mcp_request_cross = {
            'method': 'tools/call',
            'params': {
                'name': 'search_memory',
                'arguments': {
                    'namespace': 'tenant-b',
                    'query': 'test'
                }
            }
        }

        result_cross = self.invoke_request_interceptor(mcp_request_cross, context, jwt_token)
        # Check if request was denied (has transformedGatewayResponse with isError: True)
        denied = result_cross.get('mcp', {}).get('transformedGatewayResponse', {}).get('body', {}).get('result', {}).get('isError', False)
        if denied:
            print("[PASS] Cross-tenant access was rejected")
        else:
            print(f"[FAIL] Cross-tenant access was not rejected: {result_cross}")
            return False

        return True

    def test_04_invalid_jwt_scenarios(self):
        """
        Test IN-05 (ERR-01, ERR-02, ERR-03): 無効な JWT のシナリオ
        """
        print("\n[TEST IN-05] Invalid JWT Scenarios")
        print("=" * 60)

        # Test 1: Invalid JWT signature
        print("\n[1] Test with invalid JWT signature")
        invalid_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        response = self.invoke_lambda_authorizer(invalid_jwt)

        if response and response.get('isAuthorized') == False:
            print("[PASS] Invalid JWT signature was rejected")
        else:
            print(f"[FAIL] Invalid JWT should be rejected: {response}")
            return False

        # Test 2: Missing authorization header
        print("\n[2] Test with missing authorization header")
        event_no_auth = {
            'type': 'REQUEST',
            'methodArn': 'arn:aws:execute-api:us-east-1:123456789012:abcdef/*/GET/test',
            'headers': {}
        }

        try:
            response = self.lambda_client.invoke(
                FunctionName=self.authorizer_function_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(event_no_auth)
            )
            payload = json.loads(response['Payload'].read())

            if payload.get('isAuthorized') == False:
                print("[PASS] Missing authorization header was rejected")
            else:
                print(f"[FAIL] Missing auth header should be rejected: {payload}")
                return False
        except Exception as e:
            print(f"[ERROR] Test failed: {e}")
            return False

        return True

    def run_all_tests(self):
        """
        Run all Inbound Auth tests.
        """
        print("\n" + "=" * 60)
        print("PHASE 1 - Inbound Auth Integration Flow Tests")
        print("=" * 60)
        print(f"Region: {self.region}")
        print(f"User Pool: {self.user_pool_id}")
        print(f"Authorizer: {self.authorizer_function_name}")
        print(f"Interceptor: {self.interceptor_function_name}")
        print("=" * 60)

        results = {}

        # Run tests
        results['IN-01'] = self.test_01_lambda_authorizer_jwt_verification()
        results['IN-02'] = self.test_02_tenant_id_extraction()
        results['IN-03'] = self.test_03_request_interceptor_tenant_boundary()
        results['IN-05'] = self.test_04_invalid_jwt_scenarios()

        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)

        for test_id, result in results.items():
            status = "[PASS]" if result else "[FAIL]"
            print(f"{status} Test {test_id}")

        total = len(results)
        passed = sum(1 for r in results.values() if r)

        print(f"\nTotal: {total}, Passed: {passed}, Failed: {total - passed}")
        print("=" * 60)

        return all(results.values())


if __name__ == '__main__':
    # Load environment variables from .env file
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value

    tester = TestInboundAuth()
    success = tester.run_all_tests()

    sys.exit(0 if success else 1)
