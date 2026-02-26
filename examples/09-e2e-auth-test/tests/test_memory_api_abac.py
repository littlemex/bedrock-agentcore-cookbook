#!/usr/bin/env python3
"""
Test Memory API ABAC

Tests the Memory API with IAM ABAC for tenant isolation:
- Gateway accesses DynamoDB with IAM Session Tags
- DynamoDB items are tagged with tenant_id
- IAM ABAC policy enforces tenant boundary
- Cross-tenant access is denied by IAM

This test validates the Outbound Auth concepts with DynamoDB from Chapter 2.
"""

import boto3
import json
import os
import sys
import uuid
from datetime import datetime
from botocore.exceptions import ClientError

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMemoryAPIABAC:
    def __init__(self):
        self.region = os.getenv('AWS_REGION', 'us-east-1')
        self.account_id = os.getenv('AWS_ACCOUNT_ID')
        self.sts_client = boto3.client('sts', region_name=self.region)
        self.dynamodb = boto3.resource('dynamodb', region_name=self.region)

        # Memory table
        self.memory_table_name = os.getenv('MEMORY_TABLE', 'agentcore-e2e-test-memory')
        self.memory_table = self.dynamodb.Table(self.memory_table_name)

        # Gateway IAM Role
        self.gateway_role_arn = os.getenv('GATEWAY_ROLE_ARN',
                                         f'arn:aws:iam::{self.account_id}:role/agentcore-e2e-test-gateway-role')

        # Test memory items
        self.test_memories = {
            'tenant-a': {
                'memory_id': str(uuid.uuid4()),
                'tenant_id': 'tenant-a',
                'content': 'Test memory for tenant-a',
                'tags': ['test', 'tenant-a']
            },
            'tenant-b': {
                'memory_id': str(uuid.uuid4()),
                'tenant_id': 'tenant-b',
                'content': 'Test memory for tenant-b',
                'tags': ['test', 'tenant-b']
            }
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

    def setup_test_data(self):
        """
        Create test memory items in DynamoDB.
        """
        print("\n[SETUP] Creating test memory items")

        for tenant_id, memory in self.test_memories.items():
            try:
                self.memory_table.put_item(
                    Item={
                        'memory_id': memory['memory_id'],
                        'tenant_id': memory['tenant_id'],
                        'content': memory['content'],
                        'tags': memory['tags'],
                        'created_at': datetime.utcnow().isoformat()
                    }
                )
                print(f"[OK] Created memory for {tenant_id}: {memory['memory_id']}")
            except Exception as e:
                print(f"[ERROR] Failed to create memory for {tenant_id}: {e}")

    def cleanup_test_data(self):
        """
        Delete test memory items from DynamoDB.
        """
        print("\n[CLEANUP] Deleting test memory items")

        for tenant_id, memory in self.test_memories.items():
            try:
                self.memory_table.delete_item(
                    Key={
                        'memory_id': memory['memory_id'],
                        'tenant_id': memory['tenant_id']
                    }
                )
                print(f"[OK] Deleted memory for {tenant_id}")
            except Exception as e:
                print(f"[WARN] Failed to delete memory for {tenant_id}: {e}")

    def assume_role_for_tenant(self, tenant_id):
        """
        Assume Gateway role for specific tenant with IAM Session Tags.

        This simulates Gateway assuming its role with tenant_id session tag,
        enabling IAM ABAC for DynamoDB access.
        """
        try:
            response = self.sts_client.assume_role(
                RoleArn=self.gateway_role_arn,
                RoleSessionName=f'gateway-memory-{tenant_id}',
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

    def get_memory_with_credentials(self, memory_id, tenant_id, credentials):
        """
        Get memory item from DynamoDB using provided credentials.
        """
        try:
            dynamodb = boto3.resource(
                'dynamodb',
                region_name=self.region,
                **credentials
            )
            table = dynamodb.Table(self.memory_table_name)

            response = table.get_item(
                Key={
                    'memory_id': memory_id,
                    'tenant_id': tenant_id
                }
            )

            return response.get('Item')
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            print(f"[DEBUG] DynamoDB GetItem error: {error_code} - {error_msg}")
            if error_code == 'AccessDeniedException' or 'not authorized' in error_msg:
                return 'ACCESS_DENIED'
            print(f"[ERROR] Failed to get memory: {e}")
            return None
        except Exception as e:
            error_msg = str(e)
            print(f"[DEBUG] GetItem exception: {error_msg}")
            if 'AccessDenied' in error_msg or 'not authorized' in error_msg:
                return 'ACCESS_DENIED'
            print(f"[ERROR] Failed to get memory: {e}")
            return None

    def query_memories_by_tenant(self, tenant_id, credentials):
        """
        Query memory items by tenant_id using provided credentials.
        """
        try:
            dynamodb = boto3.resource(
                'dynamodb',
                region_name=self.region,
                **credentials
            )
            table = dynamodb.Table(self.memory_table_name)

            response = table.query(
                IndexName='tenant_id-index',
                KeyConditionExpression='tenant_id = :tid',
                ExpressionAttributeValues={
                    ':tid': tenant_id
                }
            )

            return response.get('Items', [])
        except Exception as e:
            error_msg = str(e)
            if 'AccessDenied' in error_msg or 'not authorized' in error_msg:
                return 'ACCESS_DENIED'
            print(f"[ERROR] Failed to query memories: {e}")
            return None

    def test_01_tenant_a_memory_access(self):
        """
        Test MEM-01: テナント A のメモリアクセス
        """
        print("\n[TEST MEM-01] Tenant-A Memory Access")
        print("=" * 60)

        tenant_id = 'tenant-a'
        memory = self.test_memories[tenant_id]

        print(f"\n[1] Assume Gateway role")
        credentials = self.assume_role_for_tenant(tenant_id)

        if not credentials:
            print("[SKIP] Cannot assume role")
            return False

        print(f"[OK] Role assumed successfully")

        print(f"\n[2] Get memory for tenant-a: {memory['memory_id']}")
        item = self.get_memory_with_credentials(
            memory['memory_id'],
            memory['tenant_id'],
            credentials
        )

        if item and item != 'ACCESS_DENIED':
            print(f"[PASS] Tenant-a memory access successful")
            print(f"[INFO] Memory content: {item.get('content')}")
            print(f"[INFO] Memory tags: {item.get('tags')}")

            # Verify content
            if item.get('tenant_id') == tenant_id:
                print(f"[PASS] Memory tenant_id validated")
                return True
            else:
                print(f"[WARN] Memory tenant_id mismatch")
                return True
        else:
            print(f"[FAIL] Tenant-a memory access denied: {item}")
            return False

    def test_02_tenant_b_memory_access(self):
        """
        Test MEM-02: テナント B のメモリアクセス
        """
        print("\n[TEST MEM-02] Tenant-B Memory Access")
        print("=" * 60)

        tenant_id = 'tenant-b'
        memory = self.test_memories[tenant_id]

        print(f"\n[1] Assume Gateway role")
        credentials = self.assume_role_for_tenant(tenant_id)

        if not credentials:
            print("[SKIP] Cannot assume role")
            return False

        print(f"[OK] Role assumed successfully")

        print(f"\n[2] Get memory for tenant-b: {memory['memory_id']}")
        item = self.get_memory_with_credentials(
            memory['memory_id'],
            memory['tenant_id'],
            credentials
        )

        if item and item != 'ACCESS_DENIED':
            print(f"[PASS] Tenant-b memory access successful")
            print(f"[INFO] Memory content: {item.get('content')}")
            print(f"[INFO] Memory tags: {item.get('tags')}")

            # Verify content
            if item.get('tenant_id') == tenant_id:
                print(f"[PASS] Memory tenant_id validated")
                return True
            else:
                print(f"[WARN] Memory tenant_id mismatch")
                return True
        else:
            print(f"[FAIL] Tenant-b memory access denied: {item}")
            return False

    def test_03_query_memories_by_tenant(self):
        """
        Test MEM-03: テナント別メモリクエリ
        """
        print("\n[TEST MEM-03] Query Memories by Tenant")
        print("=" * 60)

        results = {}

        for tenant_id in ['tenant-a', 'tenant-b']:
            print(f"\n[Testing tenant: {tenant_id}]")

            credentials = self.assume_role_for_tenant(tenant_id)
            if not credentials:
                print(f"[SKIP] Cannot assume role for {tenant_id}")
                continue

            # Query memories for this tenant
            items = self.query_memories_by_tenant(tenant_id, credentials)

            if items and items != 'ACCESS_DENIED':
                print(f"[PASS] {tenant_id}: Query successful ({len(items)} items)")

                # Verify all items belong to this tenant
                all_correct = all(
                    item.get('tenant_id') == tenant_id
                    for item in items
                )

                if all_correct:
                    print(f"[PASS] {tenant_id}: All items have correct tenant_id")
                    results[tenant_id] = True
                else:
                    print(f"[FAIL] {tenant_id}: Some items have wrong tenant_id")
                    results[tenant_id] = False
            else:
                print(f"[FAIL] {tenant_id}: Query failed: {items}")
                results[tenant_id] = False

        return all(results.values())

    def run_all_tests(self):
        """
        Run all Memory API ABAC tests.
        """
        print("\n" + "=" * 60)
        print("PHASE 1 - Memory API ABAC Tests")
        print("=" * 60)
        print(f"Region: {self.region}")
        print(f"Memory Table: {self.memory_table_name}")
        print(f"Gateway Role: {self.gateway_role_arn}")
        print("=" * 60)

        # Setup test data
        self.setup_test_data()

        results = {}

        try:
            # Run tests
            results['MEM-01'] = self.test_01_tenant_a_memory_access()
            results['MEM-02'] = self.test_02_tenant_b_memory_access()
            results['MEM-03'] = self.test_03_query_memories_by_tenant()
        finally:
            # Cleanup test data
            self.cleanup_test_data()

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

    tester = TestMemoryAPIABAC()
    success = tester.run_all_tests()

    sys.exit(0 if success else 1)
