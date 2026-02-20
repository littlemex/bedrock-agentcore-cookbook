#!/usr/bin/env python3
"""
Cognito テストユーザー作成スクリプト

このスクリプトは、PartiallyAuthorizeActions API のテスト用に
Cognito User Pool にテストユーザーを作成します。

作成するユーザー:
  1. admin-test-user (role=admin)
  2. user-test-user (role=user)

前提条件:
  - boto3 >= 1.35.0
  - gateway-config.json が存在する（Cognito User Pool ID を含む）
  - DynamoDB テーブル（AuthPolicyTable）が存在する
  - User Pool に Pre Token Generation Lambda が設定されている

Usage:
  python setup-cognito-users.py
"""

import json
import logging
import os
import sys

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError as e:
    print(f"[ERROR] Missing dependency: {e}")
    print("Install with: pip install boto3")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "gateway-config.json")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

# DynamoDB テーブル名（Phase 1 で作成されたテーブル）
DYNAMODB_TABLE_NAME = "AuthPolicyTable"

# 作成するテストユーザー
# 注意: User Pool は email をユーザー名として使用する設定のため、username = email
TEST_USERS = [
    {
        "username": "admin-test@example.com",
        "password": "AdminTest123!",
        "email": "admin-test@example.com",
        "role": "admin",
        "given_name": "Admin",
        "family_name": "Test",
    },
    {
        "username": "user-test@example.com",
        "password": "UserTest123!",
        "email": "user-test@example.com",
        "role": "user",
        "given_name": "User",
        "family_name": "Test",
    },
]


def load_config() -> dict:
    """gateway-config.json を読み込む。"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"gateway-config.json が見つかりません: {CONFIG_FILE}")
        logger.info("deploy-gateway.py を実行して Gateway をデプロイしてください")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    if "cognitoUserPoolId" not in config:
        logger.error("gateway-config.json に cognitoUserPoolId がありません")
        sys.exit(1)

    return config


def register_user_policy_in_dynamodb(dynamodb_client, username: str, role: str, tenant_id: str = "tenant-a") -> bool:
    """
    DynamoDB テーブルにユーザーのポリシー情報を登録する。

    Returns:
        登録に成功した場合 True
    """
    logger.info(f"DynamoDB にポリシー情報を登録: {username}")

    try:
        dynamodb_client.put_item(
            TableName=DYNAMODB_TABLE_NAME,
            Item={
                "user_id": {"S": username},
                "role": {"S": role},
                "tenant_id": {"S": tenant_id},
            },
        )

        logger.info(f"[OK] DynamoDB に登録完了")
        logger.info(f"     user_id: {username}")
        logger.info(f"     role: {role}")
        logger.info(f"     tenant_id: {tenant_id}")

        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "ResourceNotFoundException":
            logger.error(f"[NG] DynamoDB テーブルが見つかりません: {DYNAMODB_TABLE_NAME}")
            logger.info("Phase 1 の CDK スタックをデプロイしてください")
        else:
            logger.error(f"[NG] DynamoDB 登録エラー: {error_code} - {error_msg}")

        return False


def create_user(cognito_client, user_pool_id: str, user_info: dict) -> bool:
    """
    Cognito User Pool にユーザーを作成する。

    Returns:
        作成に成功した場合 True
    """
    username = user_info["username"]
    logger.info(f"\nユーザー作成: {username}")

    # ユーザーが既に存在するか確認
    try:
        cognito_client.admin_get_user(
            UserPoolId=user_pool_id,
            Username=username,
        )
        logger.info(f"[SKIP] ユーザーは既に存在します: {username}")
        return True

    except ClientError as e:
        if e.response["Error"]["Code"] != "UserNotFoundException":
            logger.error(f"[ERROR] ユーザー確認エラー: {e}")
            return False

    # ユーザーを作成
    try:
        # ユーザー属性の準備（標準属性のみ）
        user_attributes = [
            {"Name": "email", "Value": user_info["email"]},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "given_name", "Value": user_info["given_name"]},
            {"Name": "family_name", "Value": user_info["family_name"]},
        ]

        cognito_client.admin_create_user(
            UserPoolId=user_pool_id,
            Username=username,
            UserAttributes=user_attributes,
            TemporaryPassword=user_info["password"],
            MessageAction="SUPPRESS",  # ウェルカムメールを送信しない
        )

        logger.info(f"[OK] ユーザー作成成功: {username}")

        # パスワードを恒久的に設定
        cognito_client.admin_set_user_password(
            UserPoolId=user_pool_id,
            Username=username,
            Password=user_info["password"],
            Permanent=True,
        )

        logger.info(f"[OK] パスワード設定完了")
        logger.info(f"     Username: {username}")
        logger.info(f"     Password: {user_info['password']}")
        logger.info(f"     Email: {user_info['email']}")
        logger.info(f"     Role: {user_info['role']}")

        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"[NG] ユーザー作成エラー: {error_code} - {error_msg}")
        return False


def verify_users(cognito_client, dynamodb_client, user_pool_id: str) -> None:
    """作成したユーザーを確認する。"""
    logger.info(f"\n{'='*60}")
    logger.info("作成されたユーザーの確認")
    logger.info(f"{'='*60}\n")

    for user_info in TEST_USERS:
        username = user_info["username"]

        try:
            # Cognito からユーザー情報を取得
            response = cognito_client.admin_get_user(
                UserPoolId=user_pool_id,
                Username=username,
            )

            attributes = {attr["Name"]: attr["Value"] for attr in response.get("UserAttributes", [])}

            # DynamoDB からロール情報を取得
            dynamodb_response = dynamodb_client.get_item(
                TableName=DYNAMODB_TABLE_NAME,
                Key={"user_id": {"S": username}},
            )

            if "Item" in dynamodb_response:
                role = dynamodb_response["Item"].get("role", {}).get("S", "unknown")
                tenant_id = dynamodb_response["Item"].get("tenant_id", {}).get("S", "unknown")
            else:
                role = "not registered"
                tenant_id = "N/A"

            logger.info(f"[OK] {username}")
            logger.info(f"     Email: {attributes.get('email', 'N/A')}")
            logger.info(f"     Role (DynamoDB): {role}")
            logger.info(f"     Tenant ID (DynamoDB): {tenant_id}")
            logger.info(f"     Status: {response.get('UserStatus', 'unknown')}\n")

        except ClientError as e:
            logger.error(f"[NG] {username}: {e}")


def main():
    """メイン処理"""
    logger.info("Cognito テストユーザー作成を開始します")

    # 設定ファイルの読み込み
    config = load_config()
    user_pool_id = config["cognitoUserPoolId"]

    logger.info(f"\nUser Pool ID: {user_pool_id}")

    # AWS クライアントの初期化
    cognito_client = boto3.client("cognito-idp", region_name=REGION)
    dynamodb_client = boto3.client("dynamodb", region_name=REGION)

    # ユーザーの作成
    success_count = 0
    for user_info in TEST_USERS:
        # Cognito ユーザーの作成
        if create_user(cognito_client, user_pool_id, user_info):
            # DynamoDB にポリシー情報を登録
            if register_user_policy_in_dynamodb(
                dynamodb_client,
                user_info["username"],
                user_info["role"],
                tenant_id="tenant-a",
            ):
                success_count += 1
                logger.info("")  # 空行
            else:
                logger.warning(f"[WARN] {user_info['username']} の DynamoDB 登録に失敗しました\n")
        else:
            logger.error(f"[ERROR] {user_info['username']} の作成に失敗しました\n")

    # 作成されたユーザーの確認
    verify_users(cognito_client, dynamodb_client, user_pool_id)

    # 結果のサマリー
    logger.info(f"{'='*60}")
    logger.info("作成結果サマリー")
    logger.info(f"{'='*60}")
    logger.info(f"成功: {success_count}/{len(TEST_USERS)} ユーザー")

    if success_count == len(TEST_USERS):
        logger.info("\n[OK] 全てのユーザーが正常に作成されました")
        logger.info("\n次のステップ:")
        logger.info("  python test-partially-authorize.py")
        sys.exit(0)
    else:
        logger.error("\n[NG] 一部のユーザー作成に失敗しました")
        logger.info("エラーメッセージを確認して、User Pool の設定を見直してください")
        sys.exit(1)


if __name__ == "__main__":
    main()
