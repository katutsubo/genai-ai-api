import base64
import binascii
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from agent.logging_config import get_logger, setup_logging
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

setup_logging()
logger = get_logger(__name__)

app = FastAPI(title="catalog-agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# MCP server metadata
# ---------------------------------------------------------------------------
MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_NAME = os.environ.get("MCP_SERVER_NAME", "catalog-agent-mcp")
MCP_SERVER_VERSION = os.environ.get("MCP_SERVER_VERSION", "0.1.0")

# MCP ツール定義。
# - analyze_csv : CSV(base64) を受け取り、解析結果を JSON 文字列で返す（プログラム連携向け）。
# - process_file: exapps-proxy の mode=mcp_file が呼ぶ標準ツール。
#                 同じく CSV(base64) を受け取り、結果を人間可読な Markdown で返す。
#
# 源内アプリ（genai-web）からは exapps-proxy 経由で process_file が呼ばれる。
# 画面（フォーム）は localllm/catalog-agent/exapp.json の placeholder で定義し、
# 本サービスは HTML を一切配信しない（MCP/REST バックエンドに専念する）。
MCP_TOOLS = [
    {
        "name": "analyze_csv",
        "description": (
            "CSV ファイル (base64) を受け取り、品質チェック・データカタログ生成・"
            "Text-to-SQL 品質比較を実行し、結果を JSON で返す。"
            "questions を指定すると Text-to-SQL 比較も実行する。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "元のファイル名 (例: sample.csv)",
                },
                "content_base64": {
                    "type": "string",
                    "description": "CSV 本体を base64 エンコードした文字列",
                },
                "questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Text-to-SQL 用の質問リスト (任意)",
                },
            },
            "required": ["filename", "content_base64"],
        },
    },
    {
        "name": "process_file",
        "description": (
            "アップロードされた CSV を解析し、品質チェック結果と生成された"
            "データカタログ成果物の概要を Markdown で返す（exapps-proxy mcp_file 用）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "元のファイル名 (例: sample.csv)",
                },
                "content_type": {
                    "type": "string",
                    "description": "MIME タイプ (任意)",
                },
                "content_base64": {
                    "type": "string",
                    "description": "ファイル本体を base64 エンコードした文字列",
                },
            },
            "required": ["filename", "content_base64"],
        },
    },
]


def _serialize_default(obj):
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Not serializable: {type(obj)}")


def _result_to_jsonable(result) -> dict:
    return json.loads(json.dumps(asdict(result), default=_serialize_default))


@app.get("/")
async def root():
    """サービス情報を返す（HTML フロントエンドは廃止。画面は exapp.json で定義）。"""
    return {
        "service": "catalog-agent",
        "version": app.version,
        "ui": "genai-web (exapp.json placeholder)",
        "mcp_endpoint": "/mcp",
        "tools": [t["name"] for t in MCP_TOOLS],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    questions: str = Form(None),
):
    # Validate file type
    filename = file.filename or ""
    if not filename.endswith(".csv"):
        logger.warning(json.dumps({"event": "analyze_bad_file", "filename": filename}))
        raise HTTPException(status_code=400, detail="CSV ファイルのみ対応しています")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空のファイルです")

    # Parse questions
    parsed_questions = None
    if questions is not None:
        try:
            parsed_questions = json.loads(questions)
            if not isinstance(parsed_questions, list):
                raise ValueError("not a list")
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(
                status_code=422, detail="questions は JSON 配列である必要があります"
            )

    result = await _run_analysis(content, parsed_questions, suffix=".csv")
    return _result_to_jsonable(result)


async def _run_analysis(content: bytes, questions, suffix: str = ".csv"):
    """Write bytes to a temp file, run the orchestrator, and return the AgentResult."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from agent.orchestrator import Orchestrator

        orchestrator = Orchestrator()
        return await orchestrator.run(tmp_path, questions)
    finally:
        os.unlink(tmp_path)


@app.get("/outputs/{table_name}/{filename}")
async def get_output(table_name: str, filename: str):
    from agent.config import config

    file_path = os.path.join(config.OUTPUT_DIR, "catalog", table_name, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="ファイルが存在しません")
    return FileResponse(file_path)


# ---------------------------------------------------------------------------
# MCP (Model Context Protocol) JSON-RPC 2.0 endpoint
#
# LocalStack の mcp-lambda と同じく「単発 POST で JSON-RPC を処理する
# ステートレス実装」とし、SSE ストリーミングは使わない。
# exapps-proxy の mode=mcp_file から http://catalog-agent:8002/mcp を参照する。
# ---------------------------------------------------------------------------
def _rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _rpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _decode_csv_b64(content_b64) -> bytes:
    """base64 文字列を bytes にデコードする。厳密検証は行わない（UI 由来の改行等を許容）。"""
    if content_b64 is None:
        raise ValueError("argument 'content_base64' is required")
    try:
        raw = base64.b64decode(content_b64, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"invalid base64 in 'content_base64': {exc}")
    if not raw:
        raise ValueError("空のファイルです")
    return raw


def _render_summary_md(result) -> str:
    """AgentResult を人間可読な Markdown サマリへ整形する（mcp_file 表示用）。"""
    data = _result_to_jsonable(result)

    checks = data.get("check_results") or []
    failed = [c for c in checks if not c.get("passed")]
    errors = [c for c in failed if c.get("severity") == "error"]
    warns = [c for c in failed if c.get("severity") == "warning"]

    lines = [
        "# データ品質チェック結果",
        "",
        f"- チェック総数: {len(checks)}",
        f"- エラー: {len(errors)} / 警告: {len(warns)} / 合格: {len(checks) - len(failed)}",
    ]

    if failed:
        lines += [
            "",
            "## 指摘事項",
            "",
            "| 重要度 | ルール | メッセージ | 場所 |",
            "|---|---|---|---|",
        ]
        for c in failed:
            lines.append(
                f"| {c.get('severity', '')} | {c.get('rule_id', '')} | "
                f"{c.get('message', '')} | {c.get('location', '')} |"
            )
    else:
        lines += ["", "✅ すべての品質チェックに合格しました。"]

    catalog = data.get("catalog_outputs") or {}
    if isinstance(catalog, dict) and catalog:
        lines += ["", "## 生成されたデータカタログ成果物", ""]
        for table, files in catalog.items():
            lines.append(f"### {table}")
            if isinstance(files, dict):
                for key, path in files.items():
                    lines.append(f"- **{key}**: `{path}`")
            else:
                lines.append(f"- {files}")

    comparisons = data.get("textsql_comparison") or []
    if comparisons:
        lines += ["", "## Text-to-SQL 比較", ""]
        for i, c in enumerate(comparisons, 1):
            verdict = str(c.get("verdict", "")).upper()
            lines.append(f"- Q{i}: {c.get('question', '')} → **{verdict}**")

    for e in data.get("errors") or []:
        lines.append(f"- ⚠️ {e}")

    return "\n".join(lines) + "\n"


async def _mcp_call_analyze_csv(arguments: dict) -> str:
    filename = arguments.get("filename")
    content_b64 = arguments.get("content_base64")
    questions = arguments.get("questions")

    if not filename or content_b64 is None:
        raise ValueError("arguments 'filename' and 'content_base64' are required")
    if not str(filename).endswith(".csv"):
        raise ValueError("CSV ファイルのみ対応しています (filename must end with .csv)")

    raw = _decode_csv_b64(content_b64)

    if questions is not None and not isinstance(questions, list):
        raise ValueError("questions は文字列の配列である必要があります")

    result = await _run_analysis(raw, questions, suffix=".csv")
    return json.dumps(_result_to_jsonable(result), ensure_ascii=False)


async def _mcp_call_process_file(arguments: dict) -> str:
    """exapps-proxy mode=mcp_file から呼ばれる。CSV を解析して Markdown サマリを返す。"""
    filename = arguments.get("filename") or "upload.csv"
    # exapps-proxy は content_base64 を送る。念のため他キーもフォールバックで受ける。
    content_b64 = (
        arguments.get("content_base64")
        or arguments.get("content")
        or arguments.get("file_content")
    )

    if not str(filename).endswith(".csv"):
        raise ValueError("CSV ファイルのみ対応しています (filename must end with .csv)")

    raw = _decode_csv_b64(content_b64)
    result = await _run_analysis(raw, None, suffix=".csv")
    return _render_summary_md(result)


async def _handle_mcp_rpc(req):
    """Process a single JSON-RPC request. Returns None for notifications."""
    if not isinstance(req, dict):
        return _rpc_error(None, -32600, "Invalid Request")

    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return _rpc_result(
            req_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION},
            },
        )

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": MCP_TOOLS})

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments", {}) or {}
        try:
            if name == "analyze_csv":
                text = await _mcp_call_analyze_csv(arguments)
            elif name == "process_file":
                text = await _mcp_call_process_file(arguments)
            else:
                return _rpc_error(req_id, -32602, f"unknown tool: {name}")
        except ValueError as exc:
            return _rpc_error(req_id, -32602, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.error(json.dumps({"event": "mcp_tool_error", "error": str(exc)}))
            return _rpc_error(req_id, -32603, f"internal error: {exc}")
        return _rpc_result(req_id, {"content": [{"type": "text", "text": text}]})

    return _rpc_error(req_id, -32601, f"Method not found: {method}")


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid json"})

    # バッチ (配列) リクエスト
    if isinstance(payload, list):
        if not payload:
            return JSONResponse(status_code=400, content={"error": "empty batch"})
        responses = [r for r in [await _handle_mcp_rpc(p) for p in payload] if r is not None]
        if not responses:
            return Response(status_code=202)
        return JSONResponse(content=responses)

    # 単一リクエスト
    response = await _handle_mcp_rpc(payload)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(content=response)
