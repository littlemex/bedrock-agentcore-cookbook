#!/usr/bin/env python3
"""
Test Outbound Auth - Secrets Manager ABAC

Tests the Outbound Auth flow with IAM Session Tags:
- Gateway assumes IAM role with tenant_id session tag
- Access to Secrets Manager secrets is controlled by IAM ABAC policy
- Cross-tenant access is denied by IAM policy

This test validates the Outbound Auth concepts from Chapter 2.
"""

import boto3
import json
import os
import sys
from botocore.exceptions import ClientError

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOutboundAuthSecretsManager:
    def __init__(self):
        self.region = os.getenv('AWS_REGION', 'us-east-1')
        self.account_id = os.getenv('AWS_ACCOUNT_ID')

        # Force fresh credentials by creating new session
        session = boto3.Session()
        self.sts_client = session.client('sts', region_name=self.region)
        self.secretsmanager_client = session.client('secretsmanager', region_name=self.region)

        # Gateway IAM Role (simulates Gateway's role)
        self.gateway_role_arn = os.getenv('GATEWAY_ROLE_ARN',
                                         f'arn:aws:iam::{self.account_id}:role/agentcore-e2e-test-gateway-role')

        # Test secrets
        self.test_secrets = {
            'tenant-a': f'tenant-a/service-account/google-api',
            'tenant-b': f'tenant-b/service-account/google-api'
        }

        # Refresh credentials to bypass EC2 instance metadata cache
        self._refresh_credentials()

    def _refresh_credentials(self):
        """
        Refresh credentials by assuming current role to bypass EC2 cache.

        EC2 instance metadata credentials are cached and may not reflect
        recent IAM policy changes. This method gets fresh credentials by
        explicitly assuming the current role.
        """
        try:
            # Get current identity
            caller_identity = self.sts_client.get_caller_identity()
            current_arn = caller_identity['Arn']

            # Extract role name from assumed-role ARN
            # Format: arn:aws:sts::ACCOUNT:assumed-role/ROLE_NAME/SESSION_NAME
            if 'assumed-role' in current_arn:
                parts = current_arn.split('/')
                role_name = parts[1]
                account_id = current_arn.split(':')[4]
                role_arn = f'arn:aws:iam::{account_id}:role/{role_name}'

                print(f"[INFO] Refreshing credentials for role: {role_name}")

                # Assume current role to get fresh credentials
                response = self.sts_client.assume_role(
                    RoleArn=role_arn,
                    RoleSessionName='e2e-test-fresh-session'
                )

                credentials = response['Credentials']

                # Create new STS client with fresh credentials
                self.sts_client = boto3.client(
                    'sts',
                    region_name=self.region,
                    aws_access_key_id=credentials['AccessKeyId'],
                    aws_secret_access_key=credentials['SecretAccessKey'],
                    aws_session_token=credentials['SessionToken']
                )

                print(f"[OK] Credentials refreshed successfully")
            else:
                print(f"[INFO] Not running as assumed role, skipping refresh")
        except Exception as e:
            print(f"[WARN] Failed to refresh credentials: {e}")
            print(f"[INFO] Continuing with cached credentials")

    def assume_role_for_tenant(self, tenant_id):
        """
        Assume Gateway role for specific tenant with IAM Session Tags.

        This simulates Gateway assuming its role with tenant_id session tag,
        enabling IAM ABAC for Outbound Auth.
        """
        try:
            response = self.sts_client.assume_role(
                RoleArn=self.gateway_role_arn,
                RoleSessionName=f'gateway-session-{tenant_id}',
                Tags=[
                    {
                        'Key': 'tenant_id',
                        'Value': tenant_id
                    }
                ],
                TransitiveTagKeys=['tenant_id']  # Make tag available in resource policies
            )

            credentials = response['Credentials']
            return {
                'aws_access_key_id': credentials['AccessKeyId'],
                'aws_secret_access_key': credentials['SecretAccessKey'],
                'aws_session_token': credentials['SessionToken']
            }
        except Exception as e:
            print(f"[ERROR] Failed to assume role: {e}")
            return None

    def get_secret_with_credentials(self, secret_name, credentials):
        """
        Get secret from Secrets Manager using provided credentials.

        Returns the secret value if access is allowed, None otherwise.
        """
        try:
            client = boto3.client(
                'secretsmanager',
                region_name=self.region,
                **credentials
            )

            response = client.get_secret_value(SecretId=secret_name)
            return response.get('SecretString')
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AccessDeniedException':
                return 'ACCESS_DENIED'
            print(f"[ERROR] Failed to get secret: {e}")
            return None
        except Exception as e:
            print(f"[ERROR] Failed to get secret: {e}")
            return None

    def test_01_tenant_a_secret_access(self):
        """
        Test OUT-01: テナント A のシークレットアクセス
        """
        print("\n[TEST OUT-01] Tenant-A Secret Access")
        print("=" * 60)

        tenant_id = 'tenant-a'
        secret_name = self.test_secrets[tenant_id]

        print(f"\n[1] Assume Gateway role")
        credentials = self.assume_role_for_tenant(tenant_id)

        if not credentials:
            print("[SKIP] Cannot assume role")
            return False

        print(f"[OK] Role assumed successfully")

        print(f"\n[2] Access tenant-a secret: {secret_name}")
        secret_value = self.get_secret_with_credentials(secret_name, credentials)

        if secret_value and secret_value != 'ACCESS_DENIED':
            print(f"[PASS] Tenant-a secret access successful")
            print(f"[INFO] Secret retrieved: {secret_value[:80]}...")

            # Verify secret content
            try:
                secret_data = json.loads(secret_value)
                if 'tenant-a' in str(secret_data):
                    print(f"[PASS] Secret content validated for tenant-a")
                    return True
                else:
                    print(f"[WARN] Secret content may not match tenant-a")
                    return True
            except:
                print(f"[INFO] Secret retrieved but not JSON")
                return True
        else:
            print(f"[FAIL] Tenant-a secret access denied: {secret_value}")
            return False

    def test_02_tenant_b_secret_access(self):
        """
        Test OUT-02: テナント B のシークレットアクセス
        """
        print("\n[TEST OUT-02] Tenant-B Secret Access")
        print("=" * 60)

        tenant_id = 'tenant-b'
        secret_name = self.test_secrets[tenant_id]

        print(f"\n[1] Assume Gateway role")
        credentials = self.assume_role_for_tenant(tenant_id)

        if not credentials:
            print("[SKIP] Cannot assume role")
            return False

        print(f"[OK] Role assumed successfully")

        print(f"\n[2] Access tenant-b secret: {secret_name}")
        secret_value = self.get_secret_with_credentials(secret_name, credentials)

        if secret_value and secret_value != 'ACCESS_DENIED':
            print(f"[PASS] Tenant-b secret access successful")
            print(f"[INFO] Secret retrieved: {secret_value[:80]}...")

            # Verify secret content
            try:
                secret_data = json.loads(secret_value)
                if 'tenant-b' in str(secret_data):
                    print(f"[PASS] Secret content validated for tenant-b")
                    return True
                else:
                    print(f"[WARN] Secret content may not match tenant-b")
                    return True
            except:
                print(f"[INFO] Secret retrieved but not JSON")
                return True
        else:
            print(f"[FAIL] Tenant-b secret access denied: {secret_value}")
            return False

    def test_03_multiple_tenants_secrets_exist(self):
        """
        Test OUT-03: 複数テナントのシークレット存在確認
        """
        print("\n[TEST OUT-03] Multiple Tenants Secrets Existence")
        print("=" * 60)

        results = {}

        for tenant_id in ['tenant-a', 'tenant-b']:
            print(f"\n[Testing tenant: {tenant_id}]")

            credentials = self.assume_role_for_tenant(tenant_id)
            if not credentials:
                print(f"[SKIP] Cannot assume role for {tenant_id}")
                continue

            # Test access to tenant's secret
            secret_name = self.test_secrets[tenant_id]
            secret_value = self.get_secret_with_credentials(secret_name, credentials)

            can_access = secret_value and secret_value != 'ACCESS_DENIED'
            results[tenant_id] = can_access

            if can_access:
                print(f"[PASS] {tenant_id}: Secret accessible")
                # Verify secret contains tenant-specific data
                try:
                    secret_data = json.loads(secret_value)
                    if tenant_id in str(secret_data):
                        print(f"[PASS] {tenant_id}: Secret content validated")
                    else:
                        print(f"[WARN] {tenant_id}: Secret content may not be tenant-specific")
                except:
                    pass
            else:
                print(f"[FAIL] {tenant_id}: Cannot access secret")

        # Check all tenants have accessible secrets
        all_passed = all(results.values())

        if all_passed:
            print(f"\n[PASS] All tenants have accessible secrets")
        else:
            print(f"\n[FAIL] Some tenants cannot access their secrets")

        return all_passed

    def test_04_abac_policy_enforcement(self):
        """
        Test OUT-04: IAM ABAC ポリシーの強制
        """
        print("\n[TEST OUT-04] IAM ABAC Policy Enforcement")
        print("=" * 60)

        tenant_id = 'tenant-a'

        print(f"\n[1] Assume Gateway role for tenant: {tenant_id}")
        credentials = self.assume_role_for_tenant(tenant_id)

        if not credentials:
            print("[SKIP] Cannot assume role")
            return False

        print(f"[OK] Role assumed successfully")

        # Verify ABAC policy allows access to secrets with correct prefix
        print(f"\n[2] Test access pattern for tenant-specific secrets")

        # Test 1: Access own tenant's secret (should succeed)
        own_secret = self.test_secrets[tenant_id]
        own_result = self.get_secret_with_credentials(own_secret, credentials)

        # Test 2: Access other tenant's secret (should fail)
        other_secret = self.test_secrets['tenant-b']
        other_result = self.get_secret_with_credentials(other_secret, credentials)

        can_access_own = own_result and own_result != 'ACCESS_DENIED'
        cannot_access_other = other_result == 'ACCESS_DENIED'

        if can_access_own and cannot_access_other:
            print(f"[PASS] ABAC policy correctly enforces tenant isolation")
            print(f"[INFO] Can access: {own_secret}")
            print(f"[INFO] Cannot access: {other_secret}")
            return True
        else:
            print(f"[FAIL] ABAC policy not working correctly")
            print(f"[INFO] Own secret access: {can_access_own}")
            print(f"[INFO] Cross-tenant denied: {cannot_access_other}")
            return False

    def run_all_tests(self):
        """
        Run all Outbound Auth - Secrets Manager tests.
        """
        print("\n" + "=" * 60)
        print("PHASE 1 - Outbound Auth - Secrets Manager ABAC Tests")
        print("=" * 60)
        print(f"Region: {self.region}")
        print(f"Gateway Role: {self.gateway_role_arn}")
        print(f"Test Secrets: {json.dumps(self.test_secrets, indent=2)}")
        print("=" * 60)

        results = {}

        # Run tests
        results['OUT-01'] = self.test_01_tenant_a_secret_access()
        results['OUT-02'] = self.test_02_tenant_b_secret_access()
        results['OUT-03'] = self.test_03_multiple_tenants_secrets_exist()
        results['OUT-04'] = self.test_04_abac_policy_enforcement()

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

    tester = TestOutboundAuthSecretsManager()
    success = tester.run_all_tests()

    sys.exit(0 if success else 1)
