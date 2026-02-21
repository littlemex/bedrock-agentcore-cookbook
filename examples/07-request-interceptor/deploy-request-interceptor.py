#!/usr/bin/env python3
"""
Request Interceptor のデプロイと Gateway への設定スクリプト

以下の処理を行う:
1. Request Interceptor Lambda 関数のデプロイ
2. Lambda に Gateway からの呼び出し権限を付与
3. Gateway の Request Interceptor として設定

Usage:
  python3 deploy-request-interceptor.py
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
FUNCTION_NAME = "e2e-request-interceptor"
ROLE_NAME = "e2e-request-interceptor-role"

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
            Description="Request Interceptor Lambda execution role",
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
    """Request Interceptor Lambda 関数をデプロイする。"""
    lambda_code_path = os.path.join(SCRIPT_DIR, "lambda_function.py")

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
            Description="Request Interceptor for AgentCore Gateway (RBAC tool authorization)",
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
            lambda_client.update_function_code(
                FunctionName=FUNCTION_NAME,
                ZipFile=zip_bytes,
            )
            logger.info("Lambda 関数のコードを更新しました。")
        else:
            raise

    return function_arn


def add_gateway_permission(lambda_client):
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


def update_gateway_interceptor(bedrock_client, gateway_id, request_lambda_arn, response_lambda_arn=None):
    """Gateway に Request Interceptor を設定する。"""
    try:
        gw = bedrock_client.get_gateway(gatewayIdentifier=gateway_id)

        interceptor_configs = []

        # Request Interceptor
        interceptor_configs.append({
            "interceptor": {"lambda": {"arn": request_lambda_arn}},
            "interceptionPoints": ["REQUEST"],
        })

        # 既存の Response Interceptor を維持
        existing_configs = gw.get("interceptorConfigurations", [])
        for config in existing_configs:
            points = config.get("interceptionPoints", [])
            if "RESPONSE" in points:
                interceptor_configs.append(config)

        # Response Interceptor が明示的に渡された場合
        if response_lambda_arn:
            has_response = any("RESPONSE" in c.get("interceptionPoints", []) for c in interceptor_configs)
            if not has_response:
                interceptor_configs.append({
                    "interceptor": {"lambda": {"arn": response_lambda_arn}},
                    "interceptionPoints": ["RESPONSE"],
                })

        bedrock_client.update_gateway(
            gatewayIdentifier=gateway_id,
            name=gw["name"],
            roleArn=gw["roleArn"],
            protocolType=gw["protocolType"],
            authorizerType=gw["authorizerType"],
            authorizerConfiguration=gw.get("authorizerConfiguration", {}),
            interceptorConfigurations=interceptor_configs,
        )
        logger.info("[OK] Gateway に Request Interceptor を設定しました。")
        return True

    except Exception as e:
        logger.error("Gateway の設定に失敗しました: %s", e)
        return False


def main():
    logger.info("=" * 60)
    logger.info("Request Interceptor のデプロイ")
    logger.info("=" * 60)

    gateway_config = load_gateway_config()
    gateway_id = gateway_config.get("gatewayId")

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
    add_gateway_permission(lambda_client)

    # Step 4: Gateway に Request Interceptor を設定
    logger.info("")
    logger.info("[STEP 4] Gateway に Request Interceptor を設定")
    logger.info("-" * 60)
    bedrock_client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    result = update_gateway_interceptor(bedrock_client, gateway_id, function_arn)

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
        logger.info("[OK] Request Interceptor のデプロイ完了")
    else:
        logger.info("[PARTIAL] Lambda デプロイ完了、Gateway 設定は手動で実施してください")
    logger.info("=" * 60)
    logger.info("  Function ARN: %s", function_arn)
    logger.info("  Gateway ID: %s", gateway_id)


if __name__ == "__main__":
    main()
