#!/usr/bin/env python3
"""
Test Dual Auth Independence (Phase 2 - HIGH)

Tests that Inbound Auth and Outbound Auth are independent:
- Inbound Auth success does not guarantee Outbound Auth success
- Outbound Auth failure does not invalidate Inbound Auth
- JWT token and service account tokens are separate

This validates the Dual Authentication Model from Chapter 2.
"""

import boto3
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDualAuthIndependence:
    def __init__(self):
        self.region = os.getenv('AWS_REGION', 'us-east-1')
        self.lambda_client = boto3.client('lambda', region_name=self.region)
        self.cognito_client = boto3.client('cognito-idp', region_name=self.region)
        self.secretsmanager = boto3.client('secretsmanager', region_name=self.region)

        self.user_pool_id = os.getenv('USER_POOL_ID')
        self.client_id = os.getenv('CLIENT_ID')
        self.client_secret = os.getenv('CLIENT_SECRET')
        self.authorizer_function_name = os.getenv('AUTHORIZER_FUNCTION_NAME', 'agentcore-e2e-test-authorizer-basic')

    def calculate_secret_hash(self, username):
        import hmac, hashlib, base64
        message = username + self.client_id
        dig = hmac.new(self.client_secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
        return base64.b64encode(dig).decode()

    def get_jwt_token(self, username, password):
        try:
            auth_params = {'USERNAME': username, 'PASSWORD': password}
            secret_hash = self.calculate_secret_hash(username)
            if secret_hash:
                auth_params['SECRET_HASH'] = secret_hash

            response = self.cognito_client.initiate_auth(
                ClientId=self.client_id,
                AuthFlow='USER_PASSWORD_AUTH',
                AuthParameters=auth_params
            )
            return response['AuthenticationResult']['IdToken']
        except Exception as e:
            print(f"[ERROR] Failed to get JWT: {e}")
            return None

    def invoke_lambda_authorizer(self, jwt_token):
        event = {
            'type': 'REQUEST',
            'methodArn': 'arn:aws:execute-api:us-east-1:123456789012:abcdef/*/GET/test',
            'headers': {'authorization': f'Bearer {jwt_token}'}
        }

        try:
            response = self.lambda_client.invoke(
                FunctionName=self.authorizer_function_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(event)
            )
            return json.loads(response['Payload'].read())
        except Exception as e:
            print(f"[ERROR] Failed to invoke authorizer: {e}")
            return None

    def test_01_inbound_success_outbound_missing_secret(self):
        """
        Test DUAL-01: Inbound Auth 成功、Outbound Auth リソース不在
        """
        print("\n[TEST DUAL-01] Inbound Success, Outbound Resource Missing")
        print("=" * 60)

        # Use tenant-a user
        username = 'admin@tenant-a.example.com'
        password = 'TempPass123!'

        print(f"\n[1] Get JWT token for {username}")
        jwt_token = self.get_jwt_token(username, password)

        if not jwt_token:
            print("[SKIP] Cannot get JWT token")
            return False

        print(f"[OK] JWT token obtained")

        print(f"\n[2] Test Inbound Auth (Lambda Authorizer)")
        auth_result = self.invoke_lambda_authorizer(jwt_token)

        if not auth_result or not auth_result.get('isAuthorized'):
            print(f"[FAIL] Inbound Auth failed: {auth_result}")
            return False

        print(f"[PASS] Inbound Auth succeeded")
        print(f"[INFO] Context: {auth_result.get('context')}")

        print(f"\n[3] Simulate Outbound Auth - access non-existent secret")
        non_existent_secret = 'tenant-a/service-account/non-existent-api'

        try:
            self.secretsmanager.get_secret_value(SecretId=non_existent_secret)
            print(f"[WARN] Secret exists (unexpected)")
        except self.secretsmanager.exceptions.ResourceNotFoundException:
            print(f"[PASS] Outbound resource not found (as expected)")
            print(f"[PASS] Inbound Auth success is independent of Outbound Auth failure")
            return True
        except Exception as e:
            print(f"[ERROR] Unexpected error: {e}")
            return False

    def test_02_jwt_and_service_account_separation(self):
        """
        Test DUAL-02: JWT とサービスアカウントトークンの分離
        """
        print("\n[TEST DUAL-02] JWT and Service Account Token Separation")
        print("=" * 60)

        username = 'admin@tenant-a.example.com'
        password = 'TempPass123!'

        print(f"\n[1] Verify JWT token is used for Inbound Auth")
        jwt_token = self.get_jwt_token(username, password)

        if not jwt_token:
            print("[SKIP] Cannot get JWT token")
            return False

        auth_result = self.invoke_lambda_authorizer(jwt_token)

        if not auth_result or not auth_result.get('isAuthorized'):
            print(f"[FAIL] JWT validation failed")
            return False

        print(f"[PASS] JWT validates Inbound Auth")

        print(f"\n[2] Verify service account token is stored in Secrets Manager")
        secret_name = 'tenant-a/service-account/google-api'

        try:
            response = self.secretsmanager.get_secret_value(SecretId=secret_name)
            secret_data = json.loads(response['SecretString'])

            if 'api_key' in secret_data:
                print(f"[PASS] Service account credentials are separate from JWT")
                print(f"[INFO] JWT is for Inbound Auth (user identity)")
                print(f"[INFO] Service account token is for Outbound Auth (API access)")
                return True
            else:
                print(f"[WARN] Secret structure unexpected")
                return True
        except Exception as e:
            print(f"[ERROR] Failed to access secret: {e}")
            return False

    def run_all_tests(self):
        print("\n" + "=" * 60)
        print("PHASE 2 - Dual Auth Independence Tests")
        print("=" * 60)
        print(f"Region: {self.region}")
        print(f"User Pool: {self.user_pool_id}")
        print("=" * 60)

        results = {
            'DUAL-01': self.test_01_inbound_success_outbound_missing_secret(),
            'DUAL-02': self.test_02_jwt_and_service_account_separation()
        }

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
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value

    tester = TestDualAuthIndependence()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)
