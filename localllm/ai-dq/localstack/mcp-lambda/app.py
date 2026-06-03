"""
MCP (Model Context Protocol) server for LocalStack (Lambda + API Gateway).

LocalStack の API Gateway (REST) はリクエスト/レスポンス型のため、SSE による
ストリーミングは使わず「単発 POST で JSON-RPC 2.0 を処理するステートレス実装」とする。
API Gateway の Lambda proxy 統合 event を受け取り、HTTP body の JSON-RPC メッセージを
処理して proxy 形式 (statusCode / headers / body) で返す。

対応メソッド:
  - initialize
  - notifications/initialized (および initialized) … 通知。応答ボディを返さない (202)
  - tools/list
  - tools/call
  - 未知メソッド … JSON-RPC error -32601 (Method not found)

バッチ(配列)リクエスト、event.isBase64Encoded(base64 body)にも対応する。

標準ライブラリのみで実装している(requirements.txt は空)。
"""

import base64
import binascii
import json
import os
import urllib.request
import urllib.error

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = os.environ.get("MCP_SERVER_NAME", "localstack-mcp")
SERVER_VERSION = os.environ.get("MCP_SERVER_VERSION", "0.1.0")

# LMStudio / LiteLLM の OpenAI 互換エンドポイント (list_models ツールで使用)
LMSTUDIO_BASE_URL = os.environ.get(
    "LMSTUDIO_BASE_URL", "http://host.docker.internal:1234/v1"
)
LMSTUDIO_API_KEY = os.environ.get("LMSTUDIO_API_KEY", "lm-studio")
LMSTUDIO_TIMEOUT = float(os.environ.get("LMSTUDIO_TIMEOUT", "15"))

# process_file ツールが返すテキストプレビューの最大文字数
FILE_PREVIEW_CHARS = int(os.environ.get("MCP_FILE_PREVIEW_CHARS", "2000"))


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "echo",
        "description": "入力された文字列をそのまま返す",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "add",
        "description": "2つの数値を加算する",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "list_models",
        "description": (
            "LMStudio / LiteLLM (OpenAI 互換) の /v1/models を呼び出して"
            "利用可能なモデル ID 一覧を返す。接続できない場合は空一覧を返す。"
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "process_file",
        "description": (
            "アップロードされたファイル (base64) を受け取り、その内容を解析して"
            "要約 (ファイル名・バイトサイズ・テキスト判定・行数/文字数・先頭プレビュー) "
            "を JSON 文字列で返す。テキストとしてデコードできない場合は"
            "バイナリとして扱い、プレビューは省略する。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "元のファイル名 (例: report.txt)",
                },
                "content_base64": {
                    "type": "string",
                    "description": "ファイル本体を base64 エンコードした文字列",
                },
                "content_type": {
                    "type": "string",
                    "description": "MIME タイプ (任意, 例: text/plain)",
                },
            },
            "required": ["filename", "content_base64"],
        },
    },
]


def _tool_echo(args):
    return str(args.get("text", ""))


def _tool_add(args):
    if "a" not in args or "b" not in args:
        raise ValueError("arguments 'a' and 'b' are required")
    return str(args["a"] + args["b"])


def _tool_list_models(_args):
    """LMStudio/LiteLLM の /v1/models を叩いてモデル ID 一覧を返す。

    接続失敗・タイムアウト・パース失敗時は安全に空一覧へフォールバックする
    (ツール呼び出し自体は失敗させない)。
    """
    url = LMSTUDIO_BASE_URL.rstrip("/") + "/models"
    req = urllib.request.Request(
        url,
        headers={"Authorization": "Bearer " + LMSTUDIO_API_KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=LMSTUDIO_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:  # noqa: BLE001
        return json.dumps(
            {"models": [], "error": "could not reach %s: %s" % (url, exc)},
            ensure_ascii=False,
        )

    data = payload.get("data", []) if isinstance(payload, dict) else []
    models = [m.get("id") for m in data if isinstance(m, dict) and m.get("id")]
    return json.dumps({"models": models}, ensure_ascii=False)


def _tool_process_file(args):
    """アップロードされたファイル (base64) を受け取り要約して返す。

    戻り値は JSON 文字列。最低限以下を含む:
      - filename       : 受け取ったファイル名
      - content_type   : 渡された MIME タイプ (任意)
      - size_bytes     : デコード後のバイト数
      - is_text        : UTF-8 テキストとしてデコードできたか
      - char_count     : (テキスト時) 文字数
      - line_count     : (テキスト時) 行数
      - preview        : (テキスト時) 先頭 FILE_PREVIEW_CHARS 文字
      - preview_truncated : プレビューが切り詰められたか

    必須引数が無い場合は ValueError を送出 (JSON-RPC -32602 になる)。
    base64 が不正な場合も ValueError として扱う。
    """
    filename = args.get("filename")
    content_b64 = args.get("content_base64")
    if not filename or content_b64 is None:
        raise ValueError(
            "arguments 'filename' and 'content_base64' are required"
        )

    try:
        # validate=True で不正文字を検出する
        raw = base64.b64decode(content_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 in 'content_base64': %s" % exc)

    summary = {
        "filename": str(filename),
        "content_type": args.get("content_type") or args.get("mime_type"),
        "size_bytes": len(raw),
    }

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        summary["is_text"] = False
    else:
        preview = text[:FILE_PREVIEW_CHARS]
        summary.update(
            {
                "is_text": True,
                "char_count": len(text),
                "line_count": text.count("\n") + (1 if text else 0),
                "preview": preview,
                "preview_truncated": len(text) > FILE_PREVIEW_CHARS,
            }
        )

    return json.dumps(summary, ensure_ascii=False)


TOOL_IMPLS = {
    "echo": _tool_echo,
    "add": _tool_add,
    "list_models": _tool_list_models,
    "process_file": _tool_process_file,
}


def call_tool(name, args):
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        raise ValueError("unknown tool: %s" % name)
    return impl(args or {})


# ---------------------------------------------------------------------------
# JSON-RPC dispatch
# ---------------------------------------------------------------------------
def _error(req_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def handle_rpc(req):
    """単一の JSON-RPC リクエストを処理する。

    通知(応答不要)の場合は None を返す。
    """
    if not isinstance(req, dict):
        return _error(None, -32600, "Invalid Request")

    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
        return _result(req_id, result)

    if method in ("notifications/initialized", "initialized"):
        # 通知には応答しない
        return None

    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments", {})
        try:
            text = call_tool(name, arguments)
        except ValueError as exc:
            return _error(req_id, -32602, str(exc))
        return _result(
            req_id, {"content": [{"type": "text", "text": text}]}
        )

    return _error(req_id, -32601, "Method not found: %s" % method)


# ---------------------------------------------------------------------------
# Lambda handler (API Gateway proxy integration)
# ---------------------------------------------------------------------------
def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False) if body != "" else "",
    }


def handler(event, context):  # noqa: ARG001
    event = event or {}
    body = event.get("body")
    if body is None:
        body = "{}"
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return _resp(400, {"error": "invalid base64 body"})

    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return _resp(400, {"error": "invalid json"})

    # バッチ (配列) リクエスト
    if isinstance(payload, list):
        if not payload:
            return _resp(400, {"error": "empty batch"})
        responses = [r for r in (handle_rpc(p) for p in payload) if r is not None]
        if not responses:
            # すべて通知だった場合は本文なし
            return _resp(202, "")
        return _resp(200, responses)

    # 単一リクエスト
    response = handle_rpc(payload)
    if response is None:
        # 通知のみ
        return _resp(202, "")
    return _resp(200, response)
