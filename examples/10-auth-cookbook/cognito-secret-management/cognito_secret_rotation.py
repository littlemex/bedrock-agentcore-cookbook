#!/usr/bin/env python3
"""
Cognito Client Secret Lifecycle Management

このスクリプトは、Cognito App Client のシークレットローテーションを
ゼロダウンタイムで実行する方法を示します。

Cognito Client Secret Lifecycle Management API（2026年2月リリース）により、
以下が可能になりました：
- 1つのApp Clientに最大2つのシークレットを同時保持（デュアルシークレット運用）
- AddUserPoolClientSecret: 新しいシークレットを追加
- DeleteUserPoolClientSecret: 古いシークレットを削除

典型的なゼロダウンタイムローテーションフロー：
1. 新しいシークレットを追加（AddUserPoolClientSecret）
2. アプリケーションを新しいシークレットに切り替え
3. 古いシークレットを削除（DeleteUserPoolClientSecret）

環境変数:
- USER_POOL_ID: Cognito User Pool ID
- CLIENT_ID: Cognito App Client ID
- AWS_REGION: AWS Region（デフォルト: us-east-1）

使用例:
    # 現在のシークレット一覧を表示
    python3 cognito_secret_rotation.py --list

    # 新しいシークレットを追加
    python3 cognito_secret_rotation.py --add

    # 古いシークレットを削除
    python3 cognito_secret_rotation.py --delete <secret-id>

    # ゼロダウンタイムローテーション（全自動）
    python3 cognito_secret_rotation.py --rotate --auto-confirm
"""

import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from typing import Dict, List, Optional

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

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
USER_POOL_ID = os.environ.get("USER_POOL_ID")
CLIENT_ID = os.environ.get("CLIENT_ID")


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
    logger.info("  AWS_REGION: %s", AWS_REGION)
    return True


def list_client_secrets(cognito_client) -> List[Dict]:
    """
    Cognito App Client の現在のシークレット一覧を取得

    Returns:
        シークレット情報のリスト
        [
            {
                "ClientSecretId": "xxxxx-xxxxx-xxxxx",
                "CreatedDate": datetime,
                "ExpiresAt": datetime  # オプション
            },
            ...
        ]
    """
    logger.info("=" * 80)
    logger.info("Cognito App Client のシークレット一覧を取得します")
    logger.info("=" * 80)

    try:
        response = cognito_client.describe_user_pool_client(
            UserPoolId=USER_POOL_ID,
            ClientId=CLIENT_ID
        )

        client_secrets = response["UserPoolClient"].get("ClientSecrets", [])
        logger.info("現在のシークレット数: %d", len(client_secrets))

        for idx, secret_info in enumerate(client_secrets, 1):
            secret_id = secret_info.get("ClientSecretId")
            created_date = secret_info.get("CreatedDate")
            expires_at = secret_info.get("ExpiresAt", "N/A")

            logger.info("  [%d] Secret ID: %s", idx, secret_id)
            logger.info("      Created: %s", created_date)
            logger.info("      Expires: %s", expires_at)

        return client_secrets

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error("[ERROR] シークレット一覧の取得に失敗: %s - %s", error_code, error_msg)
        return []


def add_client_secret(cognito_client) -> Optional[Dict]:
    """
    新しいシークレットを追加

    注意:
    - 最大2つのシークレットまで同時保持可能
    - 既に2つのシークレットがある場合はエラー

    Returns:
        追加されたシークレット情報
        {
            "ClientSecretId": "yyyyy-yyyyy-yyyyy",
            "ClientSecret": "new-secret-value"
        }
    """
    logger.info("=" * 80)
    logger.info("新しいシークレットを追加します")
    logger.info("=" * 80)

    # 現在のシークレット数を確認
    current_secrets = list_client_secrets(cognito_client)
    if len(current_secrets) >= 2:
        logger.error("[ERROR] シークレットは最大2つまでです。")
        logger.info("古いシークレットを削除してから追加してください。")
        return None

    try:
        response = cognito_client.add_user_pool_client_secret(
            UserPoolId=USER_POOL_ID,
            ClientId=CLIENT_ID
        )

        new_secret_id = response.get("ClientSecretId")
        new_secret_value = response.get("ClientSecret")

        logger.info("\n[SUCCESS] 新しいシークレットを追加しました")
        logger.info("  Secret ID: %s", new_secret_id)
        logger.info("  Secret Value: %s", new_secret_value)

        logger.info("\n[IMPORTANT] 新しいシークレット値を安全に保存してください")
        logger.info("この値は一度しか取得できません。")

        # 環境変数の例を出力
        logger.info("\n環境変数の設定例:")
        logger.info("  export CLIENT_SECRET=%s", new_secret_value)

        return {
            "ClientSecretId": new_secret_id,
            "ClientSecret": new_secret_value
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "LimitExceededException":
            logger.error("[ERROR] シークレットの最大数（2個）に達しています")
        else:
            logger.error("[ERROR] シークレットの追加に失敗: %s - %s", error_code, error_msg)

        return None


def delete_client_secret(cognito_client, secret_id: str) -> bool:
    """
    指定されたシークレットを削除

    Args:
        secret_id: 削除するシークレットのID

    注意:
    - 最低1つのシークレットは必要（全削除は不可）
    - 削除は不可逆的

    Returns:
        削除成功時 True
    """
    logger.info("=" * 80)
    logger.info("シークレットを削除します")
    logger.info("=" * 80)
    logger.info("  Secret ID: %s", secret_id)

    # 現在のシークレット数を確認
    current_secrets = list_client_secrets(cognito_client)
    if len(current_secrets) <= 1:
        logger.error("[ERROR] 最低1つのシークレットは必要です。")
        return False

    try:
        cognito_client.delete_user_pool_client_secret(
            UserPoolId=USER_POOL_ID,
            ClientId=CLIENT_ID,
            ClientSecretId=secret_id
        )

        logger.info("\n[SUCCESS] シークレットを削除しました")
        logger.info("  Secret ID: %s", secret_id)

        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]

        if error_code == "InvalidParameterException":
            logger.error("[ERROR] 最後のシークレットは削除できません")
        else:
            logger.error("[ERROR] シークレットの削除に失敗: %s - %s", error_code, error_msg)

        return False


def test_authentication(cognito_client, username: str, password: str, client_secret: str) -> bool:
    """
    指定されたシークレットで認証をテスト

    Args:
        username: ユーザー名（メールアドレス）
        password: パスワード
        client_secret: テストするシークレット

    Returns:
        認証成功時 True
    """
    logger.info("認証テスト: username=%s, secret=***", username)

    try:
        # SECRET_HASH の計算
        secret_hash = get_secret_hash(username, CLIENT_ID, client_secret)

        # InitiateAuth API
        response = cognito_client.initiate_auth(
            ClientId=CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": username,
                "PASSWORD": password,
                "SECRET_HASH": secret_hash,
            }
        )

        if "AuthenticationResult" in response:
            logger.info("[OK] 認証成功")
            return True
        else:
            logger.warning("[NG] 認証失敗: Challenge required")
            return False

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error("[NG] 認証失敗: %s - %s", error_code, error_msg)
        return False


def get_secret_hash(username: str, client_id: str, client_secret: str) -> str:
    """
    Cognito Secret Hash を計算

    Args:
        username: ユーザー名（メールアドレス）
        client_id: Cognito App Client ID
        client_secret: Cognito App Client Secret

    Returns:
        Base64エンコードされたSECRET_HASH
    """
    message = bytes(username + client_id, "utf-8")
    secret = bytes(client_secret, "utf-8")
    dig = hmac.new(secret, msg=message, digestmod=hashlib.sha256).digest()
    return base64.b64encode(dig).decode()


def rotate_secret_zero_downtime(
    cognito_client,
    test_username: Optional[str] = None,
    test_password: Optional[str] = None,
    auto_confirm: bool = False
):
    """
    ゼロダウンタイムでシークレットをローテーション

    手順:
    1. 現在のシークレット一覧を確認
    2. 新しいシークレットを追加
    3. （オプション）新しいシークレットで認証テスト
    4. 古いシークレットを削除

    Args:
        test_username: 認証テスト用ユーザー名
        test_password: 認証テスト用パスワード
        auto_confirm: 確認プロンプトをスキップ
    """
    logger.info("=" * 80)
    logger.info("ゼロダウンタイム シークレットローテーション")
    logger.info("=" * 80)

    # Step 1: 現在のシークレット一覧
    logger.info("\n[Step 1] 現在のシークレット一覧")
    current_secrets = list_client_secrets(cognito_client)
    if not current_secrets:
        logger.error("[ERROR] シークレットが見つかりません")
        return

    # Step 2: 新しいシークレットを追加
    logger.info("\n[Step 2] 新しいシークレットを追加")
    new_secret_info = add_client_secret(cognito_client)
    if not new_secret_info:
        logger.error("[ERROR] シークレットの追加に失敗しました")
        return

    new_secret_value = new_secret_info["ClientSecret"]
    new_secret_id = new_secret_info["ClientSecretId"]

    # Step 3: 認証テスト（オプション）
    if test_username and test_password:
        logger.info("\n[Step 3] 新しいシークレットで認証テスト")
        auth_success = test_authentication(cognito_client, test_username, test_password, new_secret_value)
        if not auth_success:
            logger.warning("[WARNING] 認証テストに失敗しました")
            logger.info("新しいシークレットを削除することを推奨します")
            return
    else:
        logger.info("\n[Step 3] 認証テストをスキップ（テストユーザー未指定）")

    # Step 4: 古いシークレットを削除
    logger.info("\n[Step 4] 古いシークレットを削除")

    # 削除対象のシークレットIDを特定（新しいシークレット以外）
    old_secret_ids = [s["ClientSecretId"] for s in current_secrets if s["ClientSecretId"] != new_secret_id]

    if not old_secret_ids:
        logger.info("[INFO] 削除する古いシークレットがありません")
        return

    for old_secret_id in old_secret_ids:
        logger.info("削除対象: %s", old_secret_id)

    if not auto_confirm:
        confirm = input("\n古いシークレットを削除しますか？ (yes/no): ")
        if confirm.lower() != "yes":
            logger.info("削除をキャンセルしました")
            logger.info("新しいシークレットID: %s", new_secret_id)
            return

    # 削除実行
    for old_secret_id in old_secret_ids:
        delete_success = delete_client_secret(cognito_client, old_secret_id)
        if delete_success:
            logger.info("[OK] 古いシークレットを削除しました: %s", old_secret_id)
        time.sleep(1)

    # 最終確認
    logger.info("\n[完了] シークレットローテーションが完了しました")
    logger.info("\n最新のシークレット一覧:")
    list_client_secrets(cognito_client)


def main():
    parser = argparse.ArgumentParser(
        description="Cognito Client Secret Lifecycle Management"
    )

    # サブコマンド
    parser.add_argument(
        "--list",
        action="store_true",
        help="現在のシークレット一覧を表示"
    )
    parser.add_argument(
        "--add",
        action="store_true",
        help="新しいシークレットを追加"
    )
    parser.add_argument(
        "--delete",
        metavar="SECRET_ID",
        help="指定されたシークレットを削除"
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="ゼロダウンタイムローテーション（全自動）"
    )
    parser.add_argument(
        "--test-auth",
        action="store_true",
        help="指定されたシークレットで認証テスト"
    )

    # オプション
    parser.add_argument(
        "--test-username",
        help="認証テスト用ユーザー名"
    )
    parser.add_argument(
        "--test-password",
        help="認証テスト用パスワード"
    )
    parser.add_argument(
        "--client-secret",
        help="認証テスト用シークレット"
    )
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="確認プロンプトをスキップ（自動承認）"
    )

    args = parser.parse_args()

    # 環境変数の検証
    if not validate_environment():
        sys.exit(1)

    cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)

    # --list: シークレット一覧
    if args.list:
        list_client_secrets(cognito_client)
        sys.exit(0)

    # --add: 新しいシークレットを追加
    if args.add:
        result = add_client_secret(cognito_client)
        sys.exit(0 if result else 1)

    # --delete: シークレットを削除
    if args.delete:
        success = delete_client_secret(cognito_client, args.delete)
        sys.exit(0 if success else 1)

    # --test-auth: 認証テスト
    if args.test_auth:
        if not args.test_username or not args.test_password or not args.client_secret:
            logger.error("--test-username, --test-password, --client-secret が必要です")
            sys.exit(1)

        success = test_authentication(
            cognito_client,
            args.test_username,
            args.test_password,
            args.client_secret
        )
        sys.exit(0 if success else 1)

    # --rotate: ゼロダウンタイムローテーション
    if args.rotate:
        rotate_secret_zero_downtime(
            cognito_client,
            test_username=args.test_username,
            test_password=args.test_password,
            auto_confirm=args.auto_confirm
        )
        sys.exit(0)

    # デフォルト: ヘルプを表示
    parser.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
