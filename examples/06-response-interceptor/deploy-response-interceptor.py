#!/usr/bin/env python3
"""
Response Interceptor のデプロイと Gateway への設定スクリプト

以下の処理を行う:
1. Response Interceptor Lambda 関数のデプロイ
2. Lambda に Gateway からの呼び出し権限を付与
3. Gateway の Response Interceptor として設定

前提条件:
  - boto3 >= 1.42.0
  - AWS 認証情報が設定済み
  - Gateway が作成済み (examples/03-gateway)

Usage:
  python deploy-response-interceptor.py
"""

import io
import json
import logging
import os
import sys
import time
import zipfile

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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
FUNCTION_NAME = "e2e-response-interceptor"
ROLE_NAME = "e2e-response-interceptor-role"

# Gateway の設定ファイル (04-policy-engine のものを流用)
GATEWAY_CONFIG_PATHS = [
    os.path.join(SCRIPT_DIR, "..", "04-policy-engine", "gateway-config.json"),
    os.path.join(SCRIPT_DIR, "..", "03-gateway", "gateway-config.json"),
    os.path.join(SCRIPT_DIR, "gateway-config.json"),
]


def load_gateway_config():
    """既存の Gateway 設定を読み込む。"""
    for path in GATEWAY_CONFIG_PATHS:
        if os.path.exists(path):
            with open(path) as f:
                config = json.load(f)
            logger.info("Gateway 設定を読み込みました: %s", path)
            return config
    logger.error("Gateway 設定ファイルが見つかりません。")
    logger.error("以下のいずれかのパスに gateway-config.json を配置してください:")
    for path in GATEWAY_CONFIG_PATHS:
        logger.error("  - %s", path)
    sys.exit(1)


def create_lambda_role(iam_client):
    """Lambda 実行用の IAM ロールを作成する。"""
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    try:
        response = iam_client.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Response Interceptor Lambda execution role",
        )
        role_arn = response["Role"]["Arn"]
        logger.info("IAM ロールを作成しました: %s", role_arn)

        iam_client.attach_role_policy(
            RoleName=ROLE_NAME,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )

        logger.info("IAM ロールの伝播を待機中 (10秒)...")
        time.sleep(10)
        return role_arn

    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            response = iam_client.get_role(RoleName=ROLE_NAME)
            role_arn = response["Role"]["Arn"]
            logger.info("既存の IAM ロールを使用: %s", role_arn)
            return role_arn
        raise


def deploy_lambda(lambda_client, role_arn):
    """Response Interceptor Lambda 関数をデプロイする。"""
    lambda_code_path = os.path.join(SCRIPT_DIR, "lambda_function.py")
    if not os.path.exists(lambda_code_path):
        logger.error("Lambda コードが見つかりません: %s", lambda_code_path)
        sys.exit(1)

    # ZIP パッケージ作成
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(lambda_code_path, "lambda_function.py")
    zip_buffer.seek(0)
    zip_bytes = zip_buffer.getvalue()

    try:
        response = lambda_client.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Description="Response Interceptor for AgentCore Gateway (RBAC tool filtering)",
            Timeout=30,
            MemorySize=128,
        )
        function_arn = response["FunctionArn"]
        logger.info("Lambda 関数を作成しました: %s", function_arn)

        waiter = lambda_client.get_waiter("function_active_v2")
        waiter.wait(FunctionName=FUNCTION_NAME)
        logger.info("Lambda 関数がアクティブになりました。")

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            response = lambda_client.get_function(FunctionName=FUNCTION_NAME)
            function_arn = response["Configuration"]["FunctionArn"]
            logger.info("既存の Lambda 関数を使用: %s", function_arn)

            # コードを更新
            zip_buffer.seek(0)
            lambda_client.update_function_code(
                FunctionName=FUNCTION_NAME,
                ZipFile=zip_bytes,
            )
            logger.info("Lambda 関数のコードを更新しました。")
        else:
            raise

    return function_arn


def add_gateway_permission(lambda_client, function_arn):
    """Gateway から Lambda を呼び出す権限を追加する。"""
    sts_client = boto3.client("sts", region_name=REGION)
    account_id = sts_client.get_caller_identity()["Account"]

    try:
        lambda_client.add_permission(
            FunctionName=FUNCTION_NAME,
            StatementId="AllowGatewayInvoke",
            Action="lambda:InvokeFunction",
            Principal="bedrock-agentcore.amazonaws.com",
            SourceArn=f"arn:aws:bedrock-agentcore:{REGION}:{account_id}:gateway/*",
        )
        logger.info("Gateway からの呼び出し権限を追加しました。")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            logger.info("呼び出し権限は既に設定済みです。")
        else:
            raise


def update_gateway_interceptor(bedrock_client, gateway_id, function_arn):
    """Gateway に Response Interceptor を設定する。"""
    try:
        # Gateway の現在の設定を取得
        gateway = bedrock_client.get_gateway(gatewayIdentifier=gateway_id)
        logger.info("Gateway の現在の状態: status=%s", gateway.get("status"))

        # Gateway を更新して Response Interceptor を設定
        update_params = {
            "gatewayIdentifier": gateway_id,
        }

        # Response Interceptor Lambda の設定
        # NOTE: AgentCore Gateway の update API でどのパラメータで Interceptor を設定するかは
        # API バージョンによって異なる可能性がある。
        # 公式サンプル (interceptor_deployer.py) では Gateway 作成時に指定するか、
        # update_gateway で設定する。
        logger.info("Gateway に Response Interceptor を設定します...")
        logger.info("  Gateway ID: %s", gateway_id)
        logger.info("  Lambda ARN: %s", function_arn)

        # update_gateway API で Interceptor を設定
        try:
            bedrock_client.update_gateway(
                gatewayIdentifier=gateway_id,
                responseInterceptors=[
                    {
                        "lambda": {
                            "lambdaArn": function_arn,
                        }
                    }
                ],
            )
            logger.info("[OK] Gateway に Response Interceptor を設定しました。")
            return True
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_msg = e.response["Error"]["Message"]
            logger.warning(
                "update_gateway で responseInterceptors の設定に失敗: %s - %s",
                error_code,
                error_msg,
            )
            logger.info(
                "[INFO] API が Interceptor 設定をサポートしていない可能性があります。"
            )
            logger.info(
                "  代替手段: AWS Console から Gateway の Response Interceptor を手動設定してください。"
            )
            return False

    except ClientError as e:
        logger.error("Gateway の設定に失敗しました: %s", e)
        return False


def main():
    logger.info("=" * 60)
    logger.info("Response Interceptor のデプロイ")
    logger.info("=" * 60)

    gateway_config = load_gateway_config()
    gateway_id = gateway_config.get("gatewayId")
    if not gateway_id:
        logger.error("gateway-config.json に gatewayId がありません。")
        sys.exit(1)

    # Step 1: IAM ロール作成
    logger.info("")
    logger.info("[STEP 1] IAM ロールの作成")
    logger.info("-" * 60)
    iam_client = boto3.client("iam", region_name=REGION)
    role_arn = create_lambda_role(iam_client)

    # Step 2: Lambda 関数のデプロイ
    logger.info("")
    logger.info("[STEP 2] Lambda 関数のデプロイ")
    logger.info("-" * 60)
    lambda_client = boto3.client("lambda", region_name=REGION)
    function_arn = deploy_lambda(lambda_client, role_arn)

    # Step 3: Gateway からの呼び出し権限を追加
    logger.info("")
    logger.info("[STEP 3] Gateway からの呼び出し権限を追加")
    logger.info("-" * 60)
    add_gateway_permission(lambda_client, function_arn)

    # Step 4: Gateway に Response Interceptor を設定
    logger.info("")
    logger.info("[STEP 4] Gateway に Response Interceptor を設定")
    logger.info("-" * 60)
    bedrock_client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    result = update_gateway_interceptor(bedrock_client, gateway_id, function_arn)

    # 結果の保存
    config = {
        "functionName": FUNCTION_NAME,
        "functionArn": function_arn,
        "roleArn": role_arn,
        "roleName": ROLE_NAME,
        "gatewayId": gateway_id,
        "interceptorConfigured": result,
    }
    config_path = os.path.join(SCRIPT_DIR, "interceptor-config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    logger.info("設定を保存しました: %s", config_path)

    logger.info("")
    logger.info("=" * 60)
    if result:
        logger.info("[OK] Response Interceptor のデプロイ完了")
    else:
        logger.info("[PARTIAL] Lambda デプロイ完了、Gateway 設定は手動で実施してください")
    logger.info("=" * 60)
    logger.info("  Function ARN: %s", function_arn)
    logger.info("  Gateway ID: %s", gateway_id)
    logger.info("")
    logger.info("次のステップ: python verify-response-interceptor.py")


if __name__ == "__main__":
    main()
