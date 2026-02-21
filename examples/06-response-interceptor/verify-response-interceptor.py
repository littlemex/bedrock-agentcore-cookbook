#!/usr/bin/env python3
"""
Response Interceptor の動作検証スクリプト

Lambda 関数をローカルでテスト呼び出しし、以下を検証する:
1. admin ロール: 全ツールが返却される
2. user ロール: retrieve_doc, list_tools のみ返却される
3. guest ロール: 空のツールリストが返却される
4. JWT なし: fail-closed で空のツールリストが返却される
5. tools/list 以外のレスポンス: そのまま通過する

Usage:
  python verify-response-interceptor.py [--remote]
"""

import argparse
import base64
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
FUNCTION_NAME = "e2e-response-interceptor"


def create_mock_jwt(role="user", tenant_id="tenant-a", user_id="user-1"):
    """テスト用の JWT トークンを生成する (署名なし)。"""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()

    payload = base64.urlsafe_b64encode(
        json.dumps({
            "sub": user_id,
            "role": role,
            "tenant_id": tenant_id,
            "iss": "https://cognito-idp.us-east-1.amazonaws.com/test-pool",
            "client_id": "test-client-id",
            "token_use": "access",
        }).encode()
    ).rstrip(b"=").decode()

    signature = base64.urlsafe_b64encode(b"test-signature").rstrip(b"=").decode()

    return f"Bearer {header}.{payload}.{signature}"


def create_tools_list_event(auth_header=None):
    """tools/list レスポンスのモックイベントを生成する。"""
    tools = [
        {
            "name": "mcp-target___retrieve_doc",
            "description": "Retrieve a document by ID",
            "inputSchema": {
                "type": "object",
                "properties": {"doc_id": {"type": "string"}},
                "required": ["doc_id"],
            },
        },
        {
            "name": "mcp-target___delete_data_source",
            "description": "Delete a data source",
            "inputSchema": {
                "type": "object",
                "properties": {"source_id": {"type": "string"}},
                "required": ["source_id"],
            },
        },
        {
            "name": "mcp-target___sync_data_source",
            "description": "Synchronize a data source",
            "inputSchema": {
                "type": "object",
                "properties": {"source_id": {"type": "string"}},
                "required": ["source_id"],
            },
        },
        {
            "name": "mcp-target___list_tools",
            "description": "List available tools",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
    ]

    event = {
        "mcp": {
            "gatewayResponse": {
                "headers": {"Content-Type": "application/json"},
                "body": {
                    "jsonrpc": "2.0",
                    "result": {"tools": tools},
                    "id": 1,
                },
            },
            "gatewayRequest": {
                "headers": {},
            },
        }
    }

    if auth_header:
        event["mcp"]["gatewayRequest"]["headers"]["authorization"] = auth_header

    return event


def create_non_tools_event():
    """tools/list 以外のレスポンスのモックイベントを生成する。"""
    return {
        "mcp": {
            "gatewayResponse": {
                "headers": {"Content-Type": "application/json"},
                "body": {
                    "jsonrpc": "2.0",
                    "result": {
                        "content": [
                            {"type": "text", "text": "Hello, world!"}
                        ]
                    },
                    "id": 2,
                },
            },
            "gatewayRequest": {
                "headers": {
                    "authorization": create_mock_jwt("user"),
                },
            },
        }
    }


def invoke_local(event):
    """Lambda 関数をローカルで呼び出す。"""
    sys.path.insert(0, SCRIPT_DIR)
    from lambda_function import lambda_handler
    return lambda_handler(event, None)


def invoke_remote(event, lambda_client):
    """Lambda 関数をリモートで呼び出す。"""
    response = lambda_client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(event),
    )
    payload = json.loads(response["Payload"].read())
    return payload


def run_test(test_name, event, invoke_fn, expected_tool_count=None, expect_passthrough=False):
    """テストを実行し結果を返す。"""
    logger.info("--- Test: %s ---", test_name)

    try:
        result = invoke_fn(event)

        if "mcp" not in result:
            logger.error("  [FAIL] レスポンスに 'mcp' キーがありません")
            return False

        transformed = result["mcp"].get("transformedGatewayResponse", {})
        body = transformed.get("body", {})

        if expect_passthrough:
            # tools/list 以外のレスポンスはそのまま通過するべき
            content = body.get("result", {}).get("content")
            if content:
                logger.info("  [PASS] レスポンスがそのまま通過しました")
                return True
            else:
                logger.error("  [FAIL] レスポンスが予期せず変更されました")
                return False

        # tools/list レスポンスの検証
        tools = body.get("result", {}).get("tools", [])
        actual_count = len(tools)

        logger.info("  interceptorOutputVersion: %s", result.get("interceptorOutputVersion"))
        logger.info("  tools count: %d (expected: %s)", actual_count, expected_tool_count)

        if expected_tool_count is not None and actual_count != expected_tool_count:
            logger.error(
                "  [FAIL] ツール数が不一致: expected=%d, actual=%d",
                expected_tool_count,
                actual_count,
            )
            return False

        # JSON-RPC 構造の検証
        if "jsonrpc" not in body:
            logger.warning("  [WARNING] body に 'jsonrpc' フィールドがありません")

        if "id" not in body:
            logger.warning("  [WARNING] body に 'id' フィールドがありません")

        logger.info("  [PASS]")
        return True

    except Exception as e:
        logger.error("  [FAIL] 例外が発生: %s", e)
        return False


def main():
    parser = argparse.ArgumentParser(description="Response Interceptor の検証")
    parser.add_argument("--remote", action="store_true", help="リモートの Lambda を呼び出す")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Response Interceptor の動作検証")
    logger.info("=" * 60)
    logger.info("モード: %s", "リモート" if args.remote else "ローカル")

    if args.remote:
        try:
            import boto3
            lambda_client = boto3.client("lambda", region_name=REGION)
            invoke_fn = lambda event: invoke_remote(event, lambda_client)
        except ImportError:
            logger.error("リモート実行には boto3 が必要です。")
            sys.exit(1)
    else:
        invoke_fn = invoke_local

    results = []

    # Test 1: admin ロール (全ツール返却)
    event = create_tools_list_event(create_mock_jwt("admin"))
    results.append(("admin: 全ツール返却", run_test("admin: 全ツール返却", event, invoke_fn, expected_tool_count=4)))

    # Test 2: user ロール (retrieve_doc, list_tools のみ)
    event = create_tools_list_event(create_mock_jwt("user"))
    results.append(("user: 2ツール返却", run_test("user: 2ツール返却", event, invoke_fn, expected_tool_count=2)))

    # Test 3: guest ロール (空リスト)
    event = create_tools_list_event(create_mock_jwt("guest"))
    results.append(("guest: 空リスト", run_test("guest: 空リスト", event, invoke_fn, expected_tool_count=0)))

    # Test 4: JWT なし (fail-closed)
    event = create_tools_list_event(auth_header=None)
    results.append(("JWT なし: fail-closed", run_test("JWT なし: fail-closed", event, invoke_fn, expected_tool_count=0)))

    # Test 5: 不正な JWT (fail-closed)
    event = create_tools_list_event(auth_header="Bearer invalid.token")
    results.append(("不正 JWT: fail-closed", run_test("不正 JWT: fail-closed", event, invoke_fn, expected_tool_count=0)))

    # Test 6: 未知のロール (空リスト)
    event = create_tools_list_event(create_mock_jwt("unknown_role"))
    results.append(("未知ロール: 空リスト", run_test("未知ロール: 空リスト", event, invoke_fn, expected_tool_count=0)))

    # Test 7: tools/list 以外のレスポンス (通過)
    event = create_non_tools_event()
    results.append(("非tools/list: 通過", run_test("非tools/list: 通過", event, invoke_fn, expect_passthrough=True)))

    # 結果サマリー
    logger.info("")
    logger.info("=" * 60)
    logger.info("検証結果サマリー")
    logger.info("=" * 60)

    pass_count = 0
    fail_count = 0
    for name, passed in results:
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
