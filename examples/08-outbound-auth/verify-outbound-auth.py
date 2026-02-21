#!/usr/bin/env python3
"""
Gateway Outbound Auth の検証スクリプト

以下を検証する:
1. OAuth2 Credential Provider API の利用可否
2. API Key Credential Provider API の利用可否
3. サポートされるベンダーの一覧取得
4. Gateway Target の credentialProviderConfigurations の構造確認
5. OAuth2 Credential Provider の作成・削除テスト

Usage:
  python3 verify-outbound-auth.py
"""

import json
import logging
import os
import sys

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("[ERROR] boto3 が必要です。pip install boto3 を実行してください。")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
TEST_PROVIDER_NAME = "e2e-test-outbound-auth-provider"


def test_api_availability(client):
    """API の利用可否を確認する。"""
    logger.info("--- Test 1: API の利用可否 ---")

    results = []

    # OAuth2 Credential Provider - list
    try:
        resp = client.list_oauth2_credential_providers(maxResults=10)
        providers = resp.get("credentialProviders", [])
        logger.info("  [PASS] list_oauth2_credential_providers: %d providers", len(providers))
        results.append(("list_oauth2_credential_providers", True))
    except Exception as e:
        logger.error("  [FAIL] list_oauth2_credential_providers: %s", e)
        results.append(("list_oauth2_credential_providers", False))

    # API Key Credential Provider - list
    try:
        resp = client.list_api_key_credential_providers(maxResults=10)
        providers = resp.get("credentialProviders", [])
        logger.info("  [PASS] list_api_key_credential_providers: %d providers", len(providers))
        results.append(("list_api_key_credential_providers", True))
    except Exception as e:
        logger.error("  [FAIL] list_api_key_credential_providers: %s", e)
        results.append(("list_api_key_credential_providers", False))

    return results


def test_supported_vendors():
    """サポートされる OAuth2 ベンダーを確認する。"""
    logger.info("--- Test 2: サポートされる OAuth2 ベンダー ---")

    # boto3 のサービスモデルからベンダー一覧を取得
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    model = client._service_model
    op = model.operation_model("CreateOauth2CredentialProvider")
    input_shape = op.input_shape

    vendor_member = input_shape.members.get("credentialProviderVendor")
    if vendor_member and hasattr(vendor_member, "enum"):
        vendors = vendor_member.enum
        logger.info("  サポートベンダー数: %d", len(vendors))
        for v in vendors:
            logger.info("    - %s", v)
        return [("supported_vendors", True, vendors)]
    else:
        logger.warning("  [WARNING] ベンダー enum が取得できません")
        return [("supported_vendors", False, [])]


def test_credential_provider_types():
    """Gateway Target の credentialProviderType を確認する。"""
    logger.info("--- Test 3: credentialProviderType の確認 ---")

    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    model = client._service_model
    op = model.operation_model("CreateGatewayTarget")
    input_shape = op.input_shape

    cpc = input_shape.members.get("credentialProviderConfigurations")
    if cpc:
        element = cpc.member
        cpt = element.members.get("credentialProviderType")
        if cpt and hasattr(cpt, "enum"):
            types = cpt.enum
            logger.info("  credentialProviderType:")
            for t in types:
                logger.info("    - %s", t)
            return [("credential_provider_types", True, types)]

    return [("credential_provider_types", False, [])]


def test_create_delete_provider(client):
    """OAuth2 Credential Provider の作成・削除テスト (CustomOauth2)。"""
    logger.info("--- Test 4: OAuth2 Provider の作成・削除 ---")

    results = []

    # 作成テスト -- CustomOauth2 をダミー設定で作成
    try:
        resp = client.create_oauth2_credential_provider(
            name=TEST_PROVIDER_NAME,
            credentialProviderVendor="CustomOauth2",
            oauth2ProviderConfigInput={
                "customOauth2ProviderConfig": {
                    "clientId": "test-client-id",
                    "clientSecret": "test-client-secret",
                    "oauthDiscovery": {
                        "authorizationServerMetadata": {
                            "issuer": "https://example.com",
                            "authorizationEndpoint": "https://example.com/oauth2/authorize",
                            "tokenEndpoint": "https://example.com/oauth2/token",
                            "responseTypes": ["code"],
                        }
                    },
                }
            },
        )
        provider_arn = resp.get("credentialProviderArn", "")
        provider_name = resp.get("name", "")
        logger.info("  [PASS] OAuth2 Provider 作成成功")
        logger.info("    Name: %s", provider_name)
        logger.info("    ARN: %s", provider_arn)
        results.append(("create_oauth2_provider", True))

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        if error_code == "ConflictException":
            logger.info("  [PASS] Provider は既に存在 (ConflictException)")
            results.append(("create_oauth2_provider", True))
        else:
            logger.error("  [FAIL] OAuth2 Provider 作成失敗: %s - %s", error_code, error_msg)
            results.append(("create_oauth2_provider", False))
            return results

    except Exception as e:
        logger.error("  [FAIL] OAuth2 Provider 作成失敗: %s", e)
        results.append(("create_oauth2_provider", False))
        return results

    # 取得テスト
    try:
        resp = client.get_oauth2_credential_provider(name=TEST_PROVIDER_NAME)
        logger.info("  [PASS] OAuth2 Provider 取得成功")
        logger.info("    Vendor: %s", resp.get("credentialProviderVendor"))
        logger.info("    Status: %s", resp.get("credentialProviderStatus", "N/A"))
        results.append(("get_oauth2_provider", True))
    except Exception as e:
        logger.error("  [FAIL] OAuth2 Provider 取得失敗: %s", e)
        results.append(("get_oauth2_provider", False))

    # 削除テスト
    try:
        client.delete_oauth2_credential_provider(name=TEST_PROVIDER_NAME)
        logger.info("  [PASS] OAuth2 Provider 削除成功")
        results.append(("delete_oauth2_provider", True))
    except Exception as e:
        logger.error("  [FAIL] OAuth2 Provider 削除失敗: %s", e)
        results.append(("delete_oauth2_provider", False))

    return results


def test_api_key_provider(client):
    """API Key Credential Provider の作成・削除テスト。"""
    logger.info("--- Test 5: API Key Provider の作成・削除 ---")

    results = []
    test_name = "e2e-test-api-key-provider"

    try:
        resp = client.create_api_key_credential_provider(
            name=test_name,
            apiKey="test-api-key-value-12345",
        )
        provider_arn = resp.get("credentialProviderArn", "")
        logger.info("  [PASS] API Key Provider 作成成功")
        logger.info("    ARN: %s", provider_arn)
        results.append(("create_api_key_provider", True))
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ConflictException":
            logger.info("  [PASS] API Key Provider は既に存在")
            results.append(("create_api_key_provider", True))
        else:
            logger.error("  [FAIL] API Key Provider 作成失敗: %s", e)
            results.append(("create_api_key_provider", False))
            return results
    except Exception as e:
        logger.error("  [FAIL] API Key Provider 作成失敗: %s", e)
        results.append(("create_api_key_provider", False))
        return results

    # 削除
    try:
        client.delete_api_key_credential_provider(name=test_name)
        logger.info("  [PASS] API Key Provider 削除成功")
        results.append(("delete_api_key_provider", True))
    except Exception as e:
        logger.error("  [FAIL] API Key Provider 削除失敗: %s", e)
        results.append(("delete_api_key_provider", False))

    return results


def main():
    logger.info("=" * 60)
    logger.info("Gateway Outbound Auth の検証")
    logger.info("=" * 60)
    logger.info("リージョン: %s", REGION)

    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    all_results = []

    # Test 1: API の利用可否
    all_results.extend(test_api_availability(client))

    # Test 2: サポートベンダー
    vendor_results = test_supported_vendors()
    for name, passed, _ in vendor_results:
        all_results.append((name, passed))

    # Test 3: credentialProviderType
    type_results = test_credential_provider_types()
    for name, passed, _ in type_results:
        all_results.append((name, passed))

    # Test 4: OAuth2 Provider の作成・削除
    all_results.extend(test_create_delete_provider(client))

    # Test 5: API Key Provider の作成・削除
    all_results.extend(test_api_key_provider(client))

    # 結果サマリー
    logger.info("")
    logger.info("=" * 60)
    logger.info("検証結果サマリー")
    logger.info("=" * 60)

    pass_count = 0
    fail_count = 0
    for name, passed in all_results:
        status = "PASS" if passed else "FAIL"
        logger.info("  [%s] %s", status, name)
        if passed:
            pass_count += 1
        else:
            fail_count += 1

    logger.info("")
    logger.info("合計: %d PASS / %d FAIL", pass_count, fail_count)

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
