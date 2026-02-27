#!/usr/bin/env python3
"""
E2E Phase 3: AgentCore Gateway デプロイスクリプト

AgentCore Gateway を boto3 経由で作成し、Lambda MCP Server をターゲットとして登録する。

前提条件:
  - boto3 >= 1.42.0
  - AWS 認証情報が設定済み
  - Phase 1 の CDK スタックがデプロイ済み（Cognito User Pool）

Usage:
  python3 deploy-gateway.py [--config CONFIG_FILE]

出力:
  gateway-config.json に Gateway 情報を保存
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

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
CONFIG_FILE = os.path.join(SCRIPT_DIR, "gateway-config.json")
PHASE1_OUTPUTS = os.path.join(SCRIPT_DIR, "..", "e2e-phase1-auth", "cdk-outputs.json")

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
GATEWAY_NAME = "e2e-phase3-gateway"


def load_phase1_outputs() -> dict:
    """Phase 1 の CDK 出力を読み込む。"""
    if not os.path.exists(PHASE1_OUTPUTS):
        logger.warning(
            "Phase 1 の cdk-outputs.json が見つかりません: %s", PHASE1_OUTPUTS
        )
        logger.warning("Cognito User Pool 情報なしで続行します。")
        return {}

    with open(PHASE1_OUTPUTS) as f:
        data = json.load(f)

    return data.get("Phase1AuthStack", {})


def load_config() -> dict:
    """既存の設定ファイルを読み込む。"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config: dict) -> None:
    """設定ファイルを保存する。"""
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, default=str)
    logger.info("設定を保存しました: %s", CONFIG_FILE)


def create_lambda_target(lambda_client, function_name: str) -> str:
    """
    Lambda MCP Server 用のテスト Lambda 関数を作成する。

    この Lambda は Gateway のターゲットとして動作し、
    MCP ツール（retrieve_doc, delete_data_source, sync_data_source, list_tools）を提供する。
    """
    # インラインの Lambda コード（MCP ツールのモック実装）
    lambda_code = '''
import json

TOOLS = {
    "retrieve_doc": {
        "name": "retrieve_doc",
        "description": "Retrieve a document by ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "Document ID"}
            },
            "required": ["doc_id"]
        }
    },
    "delete_data_source": {
        "name": "delete_data_source",
        "description": "Delete a data source",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "Data source ID"}
            },
            "required": ["source_id"]
        }
    },
    "sync_data_source": {
        "name": "sync_data_source",
        "description": "Synchronize a data source",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "Data source ID"}
            },
            "required": ["source_id"]
        }
    },
    "list_tools": {
        "name": "list_tools",
        "description": "List available tools",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
}

def lambda_handler(event, context):
    """MCP Server Lambda handler."""
    body = event.get("body", {})
    if isinstance(body, str):
        body = json.loads(body)

    method = body.get("method", "")
    request_id = body.get("id", 1)

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "e2e-phase3-mcp-server", "version": "1.0.0"}
            }
        }
    elif method == "tools/list":
        tools = [
            {
                "name": name,
                "description": tool["description"],
                "inputSchema": tool["inputSchema"]
            }
            for name, tool in TOOLS.items()
        ]
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tools}
        }
    elif method == "tools/call":
        tool_name = body.get("params", {}).get("name", "")
        arguments = body.get("params", {}).get("arguments", {})
        # Remove target prefix if present
        if "___" in tool_name:
            tool_name = tool_name.split("___")[-1]
        if tool_name in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({
                                "status": "success",
                                "tool": tool_name,
                                "arguments": arguments
                            })
                        }
                    ]
                }
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Tool not found: {tool_name}"
                }
            }
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }
'''

    # Lambda 関数のパッケージ作成
    import io
    import zipfile

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("lambda_function.py", lambda_code)
    zip_buffer.seek(0)

    # IAM ロールを作成（Lambda 実行用）
    iam_client = boto3.client("iam", region_name=REGION)
    role_name = "e2e-phase3-lambda-role"
    role_arn = None

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
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="E2E Phase 3 Lambda execution role",
        )
        role_arn = response["Role"]["Arn"]
        logger.info("IAM ロールを作成しました: %s", role_arn)

        # 基本的な Lambda 実行ポリシーをアタッチ
        iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )

        # IAM ロールの伝播を待機
        logger.info("IAM ロールの伝播を待機中...")
        time.sleep(10)

    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            response = iam_client.get_role(RoleName=role_name)
            role_arn = response["Role"]["Arn"]
            logger.info("既存の IAM ロールを使用: %s", role_arn)
        else:
            raise

    # Lambda 関数の作成
    try:
        response = lambda_client.create_function(
            FunctionName=function_name,
            Runtime="python3.12",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": zip_buffer.read()},
            Description="E2E Phase 3 MCP Server Lambda",
            Timeout=30,
            MemorySize=128,
        )
        function_arn = response["FunctionArn"]
        logger.info("Lambda 関数を作成しました: %s", function_arn)

        # Lambda 関数がアクティブになるまで待機
        waiter = lambda_client.get_waiter("function_active_v2")
        waiter.wait(FunctionName=function_name)
        logger.info("Lambda 関数がアクティブになりました。")

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            response = lambda_client.get_function(FunctionName=function_name)
            function_arn = response["Configuration"]["FunctionArn"]
            logger.info("既存の Lambda 関数を使用: %s", function_arn)

            # コードを更新
            lambda_client.update_function_code(
                FunctionName=function_name,
                ZipFile=zip_buffer.getvalue() if hasattr(zip_buffer, "getvalue") else zip_buffer.read(),
            )
            logger.info("Lambda 関数のコードを更新しました。")
        else:
            raise

    return function_arn


def create_gateway(bedrock_client, gateway_name: str, phase1_outputs: dict) -> dict:
    """
    AgentCore Gateway を作成する。

    注意: AgentCore Gateway API は bedrock-agentcore-control クライアントで提供される。
    """
    # IAM ロールの準備（Lambda実行ロールを流用）
    sts_client = boto3.client("sts", region_name=REGION)
    account_id = sts_client.get_caller_identity()["Account"]
    role_arn = f"arn:aws:iam::{account_id}:role/e2e-phase3-lambda-role"

    # Phase 1 の Cognito User Pool が利用可能な場合、Inbound Authorization を設定
    user_pool_arn = phase1_outputs.get("UserPoolArn")
    user_pool_id = phase1_outputs.get("UserPoolId")
    app_client_id = phase1_outputs.get("AppClientId")

    # Gateway 作成パラメータ
    gateway_params = {
        "name": gateway_name,
        "description": "E2E Phase 3 Gateway for Policy Engine verification",
        "roleArn": role_arn,
        "protocolType": "MCP",
        "authorizerType": "CUSTOM_JWT",
    }

    if user_pool_id and app_client_id:
        # Cognito JWT Authorizer 設定
        gateway_params["authorizerConfiguration"] = {
            "customJWTAuthorizer": {
                "allowedClients": [app_client_id],
                "discoveryUrl": f"https://cognito-idp.{REGION}.amazonaws.com/{user_pool_id}/.well-known/openid-configuration"
            }
        }
        logger.info("Cognito 認可設定を追加: UserPool=%s", user_pool_arn)
    else:
        logger.warning("Cognito 情報がないため、認可設定なしで Gateway を作成します。")

    try:
        response = bedrock_client.create_gateway(**gateway_params)
        gateway_id = response.get("gatewayId", "")
        gateway_arn = response.get("gatewayArn", "")
        logger.info("Gateway を作成しました: id=%s, arn=%s", gateway_id, gateway_arn)

        # Gateway がアクティブになるまで待機
        logger.info("Gateway のステータスを確認中...")
        for i in range(30):
            time.sleep(10)
            status_response = bedrock_client.get_gateway(gatewayIdentifier=gateway_id)
            status = status_response.get("status", "")
            logger.info("  Gateway ステータス: %s (%d/30)", status, i + 1)
            if status in ("ACTIVE", "READY", "AVAILABLE"):
                break
            if status in ("FAILED", "DELETE_FAILED"):
                raise RuntimeError(f"Gateway 作成が失敗しました: {status}")

        return {
            "gatewayId": gateway_id,
            "gatewayArn": gateway_arn,
            "status": status,
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ConflictException":
            logger.info("同名の Gateway が既に存在します。既存の Gateway を検索します。")
            return find_existing_gateway(bedrock_client, gateway_name)
        else:
            raise


def find_existing_gateway(bedrock_client, gateway_name: str) -> dict:
    """既存の Gateway を名前で検索する。"""
    try:
        response = bedrock_client.list_gateways()
        for gw in response.get("items", []):
            if gw.get("name") == gateway_name:
                gateway_id = gw["gatewayId"]
                logger.info("既存の Gateway を発見: id=%s", gateway_id)
                detail = bedrock_client.get_gateway(gatewayIdentifier=gateway_id)
                return {
                    "gatewayId": gateway_id,
                    "gatewayArn": detail.get("gatewayArn", ""),
                    "status": detail.get("status", ""),
                }
    except ClientError:
        pass

    raise RuntimeError(f"Gateway '{gateway_name}' が見つかりません。")


def add_lambda_target(bedrock_client, gateway_id: str, lambda_arn: str) -> dict:
    """Gateway に Lambda MCP Server をターゲットとして追加する。"""
    target_name = "mcp-target"

    # MCP Tool Schema の定義（Policy Engine 検証用のダミーツール）
    tool_schema = {
        "inlinePayload": [
            {
                "name": "test_policy_evaluation",
                "description": "Policy Engine evaluation test tool",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "resource": {"type": "string"}
                    },
                    "required": ["action"]
                }
            }
        ]
    }

    # Credential Provider Configuration
    credential_config = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]

    try:
        response = bedrock_client.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name=target_name,
            description="E2E Phase 3 MCP Server Target",
            targetConfiguration={
                "mcp": {
                    "lambda": {
                        "lambdaArn": lambda_arn,
                        "toolSchema": tool_schema
                    }
                }
            },
            credentialProviderConfigurations=credential_config
        )
        target_id = response.get("targetId", "")
        logger.info("Lambda ターゲットを追加しました: targetId=%s", target_id)

        # ターゲットがアクティブになるまで待機
        for i in range(20):
            time.sleep(5)
            target_status = bedrock_client.get_gateway_target(
                gatewayIdentifier=gateway_id, targetId=target_id
            )
            status = target_status.get("status", "")
            logger.info("  Target ステータス: %s (%d/20)", status, i + 1)
            if status in ("ACTIVE", "READY", "AVAILABLE"):
                break

        return {"targetId": target_id, "targetName": target_name}

    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            logger.info("ターゲットが既に存在します。")
            targets = bedrock_client.list_gateway_targets(gatewayIdentifier=gateway_id)
            for t in targets.get("items", []):
                if t.get("name") == target_name:
                    return {"targetId": t["targetId"], "targetName": target_name}
        raise


def main():
    global CONFIG_FILE

    parser = argparse.ArgumentParser(description="E2E Phase 3: Gateway デプロイ")
    parser.add_argument("--config", default=None, help="設定ファイルパス")
    parser.add_argument("--skip-lambda", action="store_true", help="Lambda 作成をスキップ")
    args = parser.parse_args()

    if args.config is not None:
        CONFIG_FILE = args.config

    logger.info("=" * 60)
    logger.info("E2E Phase 3: AgentCore Gateway デプロイ")
    logger.info("=" * 60)

    config = load_config()
    phase1_outputs = load_phase1_outputs()

    # Step 1: Lambda MCP Server の作成
    lambda_function_name = "e2e-phase3-mcp-server"
    lambda_arn = config.get("lambdaArn")

    if not args.skip_lambda:
        logger.info("")
        logger.info("[STEP 1] Lambda MCP Server の作成")
        logger.info("-" * 60)
        lambda_client = boto3.client("lambda", region_name=REGION)
        lambda_arn = create_lambda_target(lambda_client, lambda_function_name)
        config["lambdaArn"] = lambda_arn
        config["lambdaFunctionName"] = lambda_function_name
        save_config(config)
    else:
        if not lambda_arn:
            logger.error("Lambda ARN が設定されていません。--skip-lambda を外して再実行してください。")
            sys.exit(1)
        logger.info("[STEP 1] Lambda 作成をスキップ (ARN: %s)", lambda_arn)

    # Step 2: AgentCore Gateway の作成
    logger.info("")
    logger.info("[STEP 2] AgentCore Gateway の作成")
    logger.info("-" * 60)

    bedrock_client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    try:
        gateway_info = create_gateway(bedrock_client, GATEWAY_NAME, phase1_outputs)
        config["gatewayId"] = gateway_info["gatewayId"]
        config["gatewayArn"] = gateway_info["gatewayArn"]
        config["gatewayStatus"] = gateway_info["status"]
        save_config(config)
    except Exception as e:
        logger.error("Gateway 作成に失敗しました: %s", e)
        logger.info("")
        logger.info("[代替手順]")
        logger.info("  AgentCore Gateway API が利用できない場合は、以下を試してください:")
        logger.info("  1. AWS Console から手動で Gateway を作成")
        logger.info("  2. AWS 公式サンプルの setup_gateway.py を使用")
        logger.info("     https://github.com/awslabs/amazon-bedrock-agentcore-samples")
        logger.info("  3. gateway-config.json に gatewayId を手動で設定")
        logger.info("")
        logger.info("手動設定の例:")
        logger.info('  {"gatewayId": "YOUR_GATEWAY_ID", "lambdaArn": "%s"}', lambda_arn)
        save_config(config)
        sys.exit(1)

    # Step 3: Lambda ターゲットの追加
    logger.info("")
    logger.info("[STEP 3] Lambda ターゲットの追加")
    logger.info("-" * 60)

    try:
        target_info = add_lambda_target(
            bedrock_client, config["gatewayId"], lambda_arn
        )
        config["targetId"] = target_info["targetId"]
        config["targetName"] = target_info["targetName"]
        save_config(config)
    except Exception as e:
        logger.error("ターゲット追加に失敗しました: %s", e)
        logger.info("gateway-config.json に targetId を手動で設定してください。")
        save_config(config)
        sys.exit(1)

    # Phase 1 の情報を保存
    if phase1_outputs:
        config["cognitoUserPoolId"] = phase1_outputs.get("UserPoolId", "")
        config["cognitoAppClientId"] = phase1_outputs.get("AppClientId", "")
        config["cognitoUserPoolArn"] = phase1_outputs.get("UserPoolArn", "")
        save_config(config)

    logger.info("")
    logger.info("=" * 60)
    logger.info("[OK] Gateway デプロイ完了")
    logger.info("=" * 60)
    logger.info("  Gateway ID: %s", config.get("gatewayId"))
    logger.info("  Gateway ARN: %s", config.get("gatewayArn"))
    logger.info("  Target ID: %s", config.get("targetId"))
    logger.info("  Lambda ARN: %s", config.get("lambdaArn"))
    logger.info("")
    logger.info("次のステップ: python3 create-policy-engine.py")


if __name__ == "__main__":
    main()
