"""MCP ハンドラの単体テスト。

実行:
  cd localllm/ai-dq/localstack/mcp-lambda
  python -m pytest test_app.py
  # もしくは pytest 無しでも動く簡易ランナーとして:
  python test_app.py
"""

import base64
import json

import app


def _invoke(payload, is_base64=False):
    raw = json.dumps(payload)
    if is_base64:
        raw = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
    event = {"body": raw, "isBase64Encoded": is_base64}
    return app.handler(event, None)


def test_initialize():
    res = _invoke(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["id"] == 1
    assert body["result"]["protocolVersion"] == app.PROTOCOL_VERSION
    assert "tools" in body["result"]["capabilities"]


def test_initialized_notification_has_no_body():
    res = _invoke({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert res["statusCode"] == 202
    assert res["body"] == ""


def test_tools_list():
    res = _invoke({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    names = {t["name"] for t in body["result"]["tools"]}
    assert {"echo", "add"}.issubset(names)


def test_tools_call_echo():
    res = _invoke(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "hello"}},
        }
    )
    body = json.loads(res["body"])
    assert body["result"]["content"][0]["text"] == "hello"


def test_tools_call_add():
    res = _invoke(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "add", "arguments": {"a": 3, "b": 4}},
        }
    )
    body = json.loads(res["body"])
    assert body["result"]["content"][0]["text"] == "7"


def test_unknown_method():
    res = _invoke({"jsonrpc": "2.0", "id": 5, "method": "does/not/exist"})
    body = json.loads(res["body"])
    assert body["error"]["code"] == -32601


def test_unknown_tool():
    res = _invoke(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        }
    )
    body = json.loads(res["body"])
    assert body["error"]["code"] == -32602


def test_invalid_json():
    res = app.handler({"body": "{not json"}, None)
    assert res["statusCode"] == 400


def test_base64_body():
    res = _invoke(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}, is_base64=True
    )
    assert res["statusCode"] == 200


def test_batch():
    res = _invoke(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "add", "arguments": {"a": 1, "b": 2}},
            },
        ]
    )
    body = json.loads(res["body"])
    # 通知は応答に含まれないので 2 件
    assert isinstance(body, list)
    assert len(body) == 2


if __name__ == "__main__":
    # pytest が無くても実行できる簡易ランナー
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in funcs:
        try:
            fn()
            print("PASS", fn.__name__)
        except AssertionError as exc:  # noqa: PERF203
            failed += 1
            print("FAIL", fn.__name__, exc)
    print("\n%d/%d passed" % (len(funcs) - failed, len(funcs)))
    raise SystemExit(1 if failed else 0)
