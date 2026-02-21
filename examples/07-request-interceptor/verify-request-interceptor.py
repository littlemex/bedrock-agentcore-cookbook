#!/usr/bin/env python3
"""
Request Interceptor の動作検証スクリプト

以下を検証する:
1. MCP ライフサイクルメソッド (initialize, ping 等) はバイパスされる
2. admin ロール: 全ツール呼び出し可能
3. user ロール: 許可ツールのみ呼び出し可能
4. guest ロール: 全ツール拒否
5. JWT なし: 拒否
6. 不正 JWT: 拒否
7. システムツール: 認可不要

Usage:
  python3 verify-request-interceptor.py [--remote]
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
FUNCTION_NAME = "e2e-request-interceptor"


def create_mock_jwt(role="user", tenant_id="tenant-a", user_id="user-1"):
    """テスト用の JWT トークンを生成する。"""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()

    payload = base64.urlsafe_b64encode(
        json.dumps({
            "sub": user_id,
            "role": role,
            "tenant_id": tenant_id,
            "client_id": "test-client-id",
            "token_use": "access",
        }).encode()
    ).rstrip(b"=").decode()

    signature = base64.urlsafe_b64encode(b"test-signature").rstrip(b"=").decode()
    return f"Bearer {header}.{payload}.{signature}"


def create_lifecycle_event(method="initialize"):
    """MCP ライフサイクルメソッドのイベントを生成する。"""
    return {
        "mcp": {
            "gatewayRequest": {
                "headers": {"content-type": "application/json"},
                "body": {
                    "jsonrpc": "2.0",
                    "method": method,
                    "id": 1,
                },
            }
        }
    }


def create_tool_call_event(tool_name, auth_header=None, role="user"):
    """tools/call イベントを生成する。"""
    event = {
        "mcp": {
            "gatewayRequest": {
                "headers": {"content-type": "application/json"},
                "body": {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": {"test": "value"},
                    },
                    "id": 2,
                },
            }
        }
    }

    if auth_header:
        event["mcp"]["gatewayRequest"]["headers"]["authorization"] = auth_header
    elif auth_header is None and role:
        event["mcp"]["gatewayRequest"]["headers"]["authorization"] = create_mock_jwt(role)

    return event


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


def is_allowed(result):
    """レスポンスが通過 (allow) かどうかを判定する。"""
    mcp = result.get("mcp", {})
    return "transformedGatewayRequest" in mcp


def is_denied(result):
    """レスポンスが拒否 (deny) かどうかを判定する。"""
    mcp = result.get("mcp", {})
    return "transformedGatewayResponse" in mcp


def run_test(test_name, event, invoke_fn, expect_allowed=True):
    """テストを実行する。"""
    logger.info("--- Test: %s ---", test_name)

    try:
        result = invoke_fn(event)

        if expect_allowed:
            if is_allowed(result):
                logger.info("  [PASS] リクエストが通過しました")
                return True
            else:
                logger.error("  [FAIL] リクエストが予期せず拒否されました")
                body = result.get("mcp", {}).get("transformedGatewayResponse", {}).get("body", {})
                error_msg = body.get("result", {}).get("content", [{}])[0].get("text", "")
                logger.error("  Error: %s", error_msg)
                return False
        else:
            if is_denied(result):
                body = result.get("mcp", {}).get("transformedGatewayResponse", {}).get("body", {})
                error_msg = body.get("result", {}).get("content", [{}])[0].get("text", "")
                logger.info("  [PASS] リクエストが正しく拒否されました: %s", error_msg)
                return True
            else:
                logger.error("  [FAIL] リクエストが予期せず通過しました")
                return False

    except Exception as e:
        logger.error("  [FAIL] 例外が発生: %s", e)
        return False


def main():
    parser = argparse.ArgumentParser(description="Request Interceptor の検証")
    parser.add_argument("--remote", action="store_true", help="リモートの Lambda を呼び出す")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Request Interceptor の動作検証")
    logger.info("=" * 60)
    logger.info("モード: %s", "リモート" if args.remote else "ローカル")

    if args.remote:
        import boto3
        lambda_client = boto3.client("lambda", region_name=REGION)
        invoke_fn = lambda event: invoke_remote(event, lambda_client)
    else:
        invoke_fn = invoke_local

    results = []

    # Test 1: initialize (ライフサイクル) はバイパス
    event = create_lifecycle_event("initialize")
    results.append(("initialize: バイパス", run_test("initialize: バイパス", event, invoke_fn, expect_allowed=True)))

    # Test 2: ping (ライフサイクル) はバイパス
    event = create_lifecycle_event("ping")
    results.append(("ping: バイパス", run_test("ping: バイパス", event, invoke_fn, expect_allowed=True)))

    # Test 3: tools/list (ライフサイクル) はバイパス
    event = create_lifecycle_event("tools/list")
    results.append(("tools/list: バイパス", run_test("tools/list: バイパス", event, invoke_fn, expect_allowed=True)))

    # Test 4: admin + retrieve_doc (許可)
    event = create_tool_call_event("mcp-target___retrieve_doc", role="admin")
    results.append(("admin + retrieve_doc: 通過", run_test("admin + retrieve_doc: 通過", event, invoke_fn, expect_allowed=True)))

    # Test 5: admin + delete_data_source (許可)
    event = create_tool_call_event("mcp-target___delete_data_source", role="admin")
    results.append(("admin + delete_data_source: 通過", run_test("admin + delete_data_source: 通過", event, invoke_fn, expect_allowed=True)))

    # Test 6: user + retrieve_doc (許可)
    event = create_tool_call_event("mcp-target___retrieve_doc", role="user")
    results.append(("user + retrieve_doc: 通過", run_test("user + retrieve_doc: 通過", event, invoke_fn, expect_allowed=True)))

    # Test 7: user + delete_data_source (拒否)
    event = create_tool_call_event("mcp-target___delete_data_source", role="user")
    results.append(("user + delete_data_source: 拒否", run_test("user + delete_data_source: 拒否", event, invoke_fn, expect_allowed=False)))

    # Test 8: guest + retrieve_doc (拒否)
    event = create_tool_call_event("mcp-target___retrieve_doc", role="guest")
    results.append(("guest + retrieve_doc: 拒否", run_test("guest + retrieve_doc: 拒否", event, invoke_fn, expect_allowed=False)))

    # Test 9: JWT なし (拒否)
    event = create_tool_call_event("mcp-target___retrieve_doc", auth_header="", role=None)
    # auth_header を空文字で上書き
    event["mcp"]["gatewayRequest"]["headers"].pop("authorization", None)
    results.append(("JWT なし: 拒否", run_test("JWT なし: 拒否", event, invoke_fn, expect_allowed=False)))

    # Test 10: 不正 JWT (拒否)
    event = create_tool_call_event("mcp-target___retrieve_doc", auth_header="Bearer invalid.token", role=None)
    results.append(("不正 JWT: 拒否", run_test("不正 JWT: 拒否", event, invoke_fn, expect_allowed=False)))

    # Test 11: システムツール (バイパス)
    event = create_tool_call_event("x_amz_bedrock_agentcore_search", role="user")
    results.append(("システムツール: バイパス", run_test("システムツール: バイパス", event, invoke_fn, expect_allowed=True)))

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
