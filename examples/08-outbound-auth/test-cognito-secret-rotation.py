#!/usr/bin/env python3
"""
Cognito Client Secret Lifecycle Management の検証スクリプト

このスクリプトは以下を検証する:
1. CognitoOauth2ベンダーでのCredential Provider作成
2. AddUserPoolClientSecretによるシークレット追加
3. Credential ProviderのclientSecret更新
4. デュアルシークレット運用の検証
5. DeleteUserPoolClientSecretによる旧シークレット削除
6. ゼロダウンタイムの検証

前提条件:
- AWS Cognito User Poolが作成済み
- Cognito User Pool App Clientが作成済み
- 環境変数が設定済み:
  - USER_POOL_ID: Cognito User Pool ID
  - CLIENT_ID: Cognito App Client ID
  - AWS_DEFAULT_REGION: AWSリージョン

Usage:
  export USER_POOL_ID="us-east-1_XXXXXXXXX"
  export CLIENT_ID="xxxxxxxxxxxxxxxxxxxxxxxxxx"
  export AWS_DEFAULT_REGION="us-east-1"
  python3 test-cognito-secret-rotation.py
"""

import json
import logging
import os
import sys
import time

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("[ERROR] boto3が必要です。pip install boto3を実行してください。")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 環境変数
USER_POOL_ID = os.environ.get("USER_POOL_ID")
CLIENT_ID = os.environ.get("CLIENT_ID")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

# テスト用定数
TEST_PROVIDER_NAME = "e2e-test-cognito-oauth2-provider"
TEST_GATEWAY_NAME = "e2e-test-gateway-cognito"


def validate_environment():
    """環境変数のバリデーション"""
    if not USER_POOL_ID:
        logger.error("環境変数 USER_POOL_ID が設定されていません")
        return False
    if not CLIENT_ID:
        logger.error("環境変数 CLIENT_ID が設定されていません")
        return False
    logger.info("環境変数の検証: OK")
    logger.info("  USER_POOL_ID: %s", USER_POOL_ID)
    logger.info("  CLIENT_ID: %s", CLIENT_ID)
    logger.info("  REGION: %s", REGION)
    return True


def get_current_client_secrets(cognito_client):
    """
    Cognito App Clientの現在のシークレット一覧を取得する

    Returns:
        list: シークレットIDのリスト
    """
    try:
        response = cognito_client.describe_user_pool_client(
            UserPoolId=USER_POOL_ID,
            ClientId=CLIENT_ID
        )
        client_info = response.get("UserPoolClient", {})
        secret_ids = client_info.get("ClientSecretIds", [])
        logger.info("  現在のシークレット数: %d", len(secret_ids))
        for i, secret_id in enumerate(secret_ids):
            logger.info("    [%d] SecretId: %s", i + 1, secret_id)
        return secret_ids
    except ClientError as e:
        logger.error("  DescribeUserPoolClient failed: %s", e)
        return []


def test_phase1_create_cognito_oauth2_provider(agentcore_client, cognito_client):
    """
    Phase 1: CognitoOauth2ベンダーでCredential Provider作成

    この検証では、Cognito User PoolのClient IDとClient Secretを使用して
    OAuth2 Credential Providerを作成します。
    """
    logger.info("=== Phase 1: CognitoOauth2ベンダーでCredential Provider作成 ===")

    # 現在のCognito App Clientシークレットを取得
    secret_ids = get_current_client_secrets(cognito_client)
    if not secret_ids:
        logger.error("  [FAIL] Cognito App Clientにシークレットが存在しません")
        logger.info("  Note: Cognito App Clientの設定でシークレットを生成してください")
        return False

    primary_secret_id = secret_ids[0]
    logger.info("  Primary Secret ID: %s", primary_secret_id)

    # CognitoOauth2 Credential Provider作成
    # Note: Cognito OAuth2の設定には、User Pool IDとApp Client IDが必要
    try:
        # Token Endpointの構築
        token_endpoint = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"

        logger.info("  Creating CognitoOauth2 Credential Provider...")
        logger.info("    Name: %s", TEST_PROVIDER_NAME)
        logger.info("    Vendor: CognitoOauth2")
        logger.info("    ClientId: %s", CLIENT_ID)
        logger.info("    Token Endpoint: %s", token_endpoint)

        # CognitoOauth2ベンダーの正確な設定構造を確認
        # Note: この設定は boto3のサービスモデルに依存します
        response = agentcore_client.create_oauth2_credential_provider(
            name=TEST_PROVIDER_NAME,
            credentialProviderVendor="CognitoOauth2",
            oauth2ProviderConfigInput={
                "cognitoOauth2ProviderConfig": {
                    "userPoolId": USER_POOL_ID,
                    "clientId": CLIENT_ID,
                    # Note: clientSecretは実際のシークレット値を使用する必要がある
                    # DescribeUserPoolClientではシークレット値は取得できないため、
                    # 事前に環境変数またはSecrets Managerから取得する必要がある
                    # "clientSecret": "<actual-secret-value>",
                }
            },
        )

        provider_arn = response.get("credentialProviderArn", "")
        provider_id = provider_arn.split("/")[-1] if provider_arn else ""
        logger.info("  [PASS] CognitoOauth2 Provider作成成功")
        logger.info("    Provider ID: %s", provider_id)
        logger.info("    Provider ARN: %s", provider_arn)

        return provider_id

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        if error_code == "ConflictException":
            logger.info("  [INFO] Providerは既に存在します (ConflictException)")
            logger.info("    既存のProviderを使用するか、削除してから再実行してください")
            return None
        elif error_code == "ValidationException":
            logger.error("  [FAIL] 設定が不正です: %s", error_msg)
            logger.info("  Note: CognitoOauth2の設定構造がboto3のバージョンにより異なる可能性があります")
            return None
        else:
            logger.error("  [FAIL] Provider作成失敗: %s - %s", error_code, error_msg)
            return None
    except Exception as e:
        logger.error("  [FAIL] 予期しないエラー: %s", e)
        return None


def test_phase2_add_client_secret(cognito_client):
    """
    Phase 2: AddUserPoolClientSecretによるシークレット追加

    Cognito App Clientは最大2つのシークレットを保持できます。
    この検証では、新しいシークレットを追加してデュアルシークレット状態にします。
    """
    logger.info("=== Phase 2: AddUserPoolClientSecretによるシークレット追加 ===")

    # 現在のシークレット数を確認
    secret_ids = get_current_client_secrets(cognito_client)
    if len(secret_ids) >= 2:
        logger.info("  [INFO] 既に2つのシークレットが存在します（最大数）")
        logger.info("  Note: 旧シークレットを削除してから新しいシークレットを追加してください")
        return None

    try:
        logger.info("  Adding new client secret...")
        response = cognito_client.add_user_pool_client_secret(
            UserPoolId=USER_POOL_ID,
            ClientId=CLIENT_ID
        )

        # 新しいシークレットの情報を取得
        new_secret_id = response.get("ClientSecretId")
        logger.info("  [PASS] 新しいシークレットを追加しました")
        logger.info("    New Secret ID: %s", new_secret_id)
        logger.info("    Note: シークレット値は初回作成時のみ取得可能です")
        logger.info("    Note: 本番環境ではシークレット値をSecrets Managerに保存してください")

        # 更新後のシークレット一覧を確認
        logger.info("  更新後のシークレット一覧:")
        secret_ids = get_current_client_secrets(cognito_client)

        return new_secret_id

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error("  [FAIL] シークレット追加失敗: %s - %s", error_code, error_msg)
        return None


def test_phase3_update_credential_provider(agentcore_client, provider_id, new_secret):
    """
    Phase 3: Credential ProviderのclientSecret更新

    OAuth2 Credential ProviderのclientSecretを新しいシークレットに更新します。
    """
    logger.info("=== Phase 3: Credential ProviderのclientSecret更新 ===")

    if not provider_id:
        logger.error("  [SKIP] Provider IDが存在しないためスキップします")
        return False

    if not new_secret:
        logger.error("  [SKIP] 新しいシークレットが存在しないためスキップします")
        return False

    try:
        logger.info("  Updating OAuth2 Credential Provider...")
        logger.info("    Provider ID: %s", provider_id)

        # Note: update_oauth2_credential_providerのAPIシグネチャを確認
        # boto3のバージョンにより異なる可能性がある
        response = agentcore_client.update_oauth2_credential_provider(
            credentialProviderId=provider_id,
            oauth2ProviderConfigInput={
                "cognitoOauth2ProviderConfig": {
                    "clientSecret": new_secret
                }
            }
        )

        logger.info("  [PASS] Credential Providerを更新しました")
        logger.info("    Updated at: %s", response.get("lastModifiedAt"))

        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error("  [FAIL] Provider更新失敗: %s - %s", error_code, error_msg)
        logger.info("  Note: update_oauth2_credential_provider APIがサポートされているか確認してください")
        return False
    except Exception as e:
        logger.error("  [FAIL] 予期しないエラー: %s", e)
        return False


def test_phase4_dual_secret_validation(agentcore_client, provider_id):
    """
    Phase 4: デュアルシークレット運用の検証

    新旧両方のシークレットが有効な状態で、OAuth2認証が正常に動作することを検証します。
    実際の検証には、Token Vaultへのアクセスとトークン取得が必要です。
    """
    logger.info("=== Phase 4: デュアルシークレット運用の検証 ===")

    logger.info("  [INFO] この検証は実際のOAuth2フローの実行が必要です")
    logger.info("  [INFO] Token Vaultに格納されたトークンが有効かを確認します")

    # Note: 実際の検証には以下が必要:
    # 1. 旧シークレットで発行されたトークンがToken Vaultに存在すること
    # 2. 新シークレットでOAuth2 Client Credentials Grantが成功すること
    # 3. Gateway経由でOutbound Authが成功すること

    logger.info("  [TODO] Gateway Targetへの紐付けとOutbound Auth動作テスト")
    logger.info("  [TODO] 旧シークレットで発行されたトークンの有効性確認")
    logger.info("  [TODO] 新シークレットでの新規トークン取得")

    return True


def test_phase5_delete_old_secret(cognito_client, old_secret_id):
    """
    Phase 5: DeleteUserPoolClientSecretによる旧シークレット削除

    デュアルシークレット運用を終了し、旧シークレットを削除します。
    """
    logger.info("=== Phase 5: DeleteUserPoolClientSecretによる旧シークレット削除 ===")

    if not old_secret_id:
        logger.error("  [SKIP] 旧シークレットIDが存在しないためスキップします")
        return False

    try:
        logger.info("  Deleting old client secret...")
        logger.info("    Secret ID to delete: %s", old_secret_id)

        cognito_client.delete_user_pool_client_secret(
            UserPoolId=USER_POOL_ID,
            ClientId=CLIENT_ID,
            SecretId=old_secret_id
        )

        logger.info("  [PASS] 旧シークレットを削除しました")

        # 削除後のシークレット一覧を確認
        logger.info("  削除後のシークレット一覧:")
        get_current_client_secrets(cognito_client)

        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error("  [FAIL] シークレット削除失敗: %s - %s", error_code, error_msg)
        return False


def test_phase6_zero_downtime_validation(agentcore_client, provider_id):
    """
    Phase 6: ゼロダウンタイムの検証

    シークレット回転プロセス全体を通じて、Outbound Authが中断しないことを検証します。
    """
    logger.info("=== Phase 6: ゼロダウンタイムの検証 ===")

    logger.info("  [INFO] この検証は以下を確認します:")
    logger.info("    1. シークレット追加中もOutbound Authが継続")
    logger.info("    2. Credential Provider更新中もOutbound Authが継続")
    logger.info("    3. 旧シークレット削除後も新シークレットでOutbound Authが成功")

    logger.info("  [TODO] Gateway経由の継続的なリクエスト送信")
    logger.info("  [TODO] 各フェーズでのレスポンスタイム測定")
    logger.info("  [TODO] エラー率の監視（0% が期待値）")

    return True


def cleanup_test_resources(agentcore_client, cognito_client, provider_id):
    """テストリソースのクリーンアップ"""
    logger.info("=== クリーンアップ ===")

    # Credential Providerの削除
    if provider_id:
        try:
            logger.info("  Deleting OAuth2 Credential Provider...")
            agentcore_client.delete_oauth2_credential_provider(
                credentialProviderId=provider_id
            )
            logger.info("  [OK] Credential Providerを削除しました")
        except ClientError as e:
            logger.warning("  [WARNING] Provider削除失敗: %s", e)

    logger.info("  Note: Cognito User PoolとApp Clientは手動で削除してください")


def main():
    """メイン実行"""
    logger.info("=" * 80)
    logger.info("Cognito Client Secret Lifecycle Management 検証スクリプト")
    logger.info("=" * 80)

    # 環境変数の検証
    if not validate_environment():
        logger.error("環境変数の検証に失敗しました。終了します。")
        sys.exit(1)

    # AWS クライアントの初期化
    agentcore_client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    cognito_client = boto3.client("cognito-idp", region_name=REGION)

    provider_id = None
    new_secret_id = None
    old_secret_ids = get_current_client_secrets(cognito_client)

    try:
        # Phase 1: CognitoOauth2 Credential Provider作成
        provider_id = test_phase1_create_cognito_oauth2_provider(
            agentcore_client, cognito_client
        )
        if not provider_id:
            logger.warning("Phase 1がスキップされたため、後続のテストは実行できません")
            logger.info("\n" + "=" * 80)
            logger.info("検証結果サマリー")
            logger.info("=" * 80)
            logger.info("[INFO] CognitoOauth2ベンダーのサポート状況を確認してください")
            logger.info("[INFO] boto3のバージョンを最新に更新してください: pip install --upgrade boto3")
            return

        time.sleep(2)

        # Phase 2: 新しいシークレット追加
        new_secret_id = test_phase2_add_client_secret(cognito_client)
        if not new_secret_id:
            logger.warning("Phase 2がスキップされました")

        time.sleep(2)

        # Phase 3: Credential Provider更新
        if new_secret_id:
            # Note: 実際のシークレット値が必要（DescribeUserPoolClientでは取得不可）
            logger.info("\n[重要] Phase 3の実行には実際のシークレット値が必要です")
            logger.info("新しいシークレット値をSecrets Managerまたは環境変数から取得してください")
            # test_phase3_update_credential_provider(agentcore_client, provider_id, new_secret_value)

        # Phase 4: デュアルシークレット運用検証
        test_phase4_dual_secret_validation(agentcore_client, provider_id)

        # Phase 5: 旧シークレット削除
        # Note: 実際の運用では、新シークレットでの動作確認後に実行
        # if old_secret_ids and len(old_secret_ids) > 0:
        #     test_phase5_delete_old_secret(cognito_client, old_secret_ids[0])

        # Phase 6: ゼロダウンタイム検証
        test_phase6_zero_downtime_validation(agentcore_client, provider_id)

    except KeyboardInterrupt:
        logger.info("\n[中断] ユーザーによりテストが中断されました")
    except Exception as e:
        logger.error("予期しないエラーが発生しました: %s", e)
    finally:
        # クリーンアップ
        cleanup_input = input("\nテストリソースをクリーンアップしますか？ (y/N): ")
        if cleanup_input.lower() == "y":
            cleanup_test_resources(agentcore_client, cognito_client, provider_id)

    logger.info("\n" + "=" * 80)
    logger.info("検証完了")
    logger.info("=" * 80)
    logger.info("[重要] 完全な検証には以下が必要です:")
    logger.info("  1. Gateway Targetへの Credential Provider紐付け")
    logger.info("  2. 実際のMCPサーバーへのOutbound Auth動作確認")
    logger.info("  3. シークレット回転中の継続的なリクエスト送信と監視")
    logger.info("  4. Token Vaultに格納されたトークンの有効性確認")


if __name__ == "__main__":
    main()
