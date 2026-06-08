import base64
import binascii
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

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
                "model": {
                    "type": "string",
                    "description": "カタログ生成に使用する LLM モデルID (任意。未指定時はサーバ既定)",
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

    result = await _run_analysis(content, parsed_questions, suffix=".csv", filename=filename)
    return _result_to_jsonable(result)

def _safe_table_name(filename: str | None, suffix: str = ".csv") -> str:
    """元ファイル名から安全なテーブル名(=出力ディレクトリ名)を作る。"""
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    # 英数字 / ハイフン / アンダースコア / ドット / 日本語以外は _ に置換
    stem = re.sub(r"[^\w\-.]", "_", stem, flags=re.UNICODE).strip("._")
    return stem or "upload"

async def _run_analysis(content: bytes, questions, suffix: str = ".csv", filename: str | None = None):
    """Write bytes to a temp file (keeping a meaningful name) and run the orchestrator."""
    tmp_dir = tempfile.mkdtemp()
    safe_name = _safe_table_name(filename, suffix) + suffix
    tmp_path = os.path.join(tmp_dir, safe_name)
    with open(tmp_path, "wb") as f:
        f.write(content)

    try:
        from agent.orchestrator import Orchestrator

        orchestrator = Orchestrator()
        return await orchestrator.run(tmp_path, questions)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/outputs/{table_name}")
async def list_outputs(table_name: str):
    """指定テーブルの生成済み成果物ファイル一覧を返す（ダウンロードUI用）。"""
    from agent.config import config

    if "/" in table_name or "\\" in table_name or table_name in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="不正なパスです")

    base_dir = os.path.realpath(os.path.join(config.OUTPUT_DIR, "catalog"))
    table_dir = os.path.realpath(os.path.join(base_dir, table_name))
    if not table_dir.startswith(base_dir + os.sep) or not os.path.isdir(table_dir):
        raise HTTPException(status_code=404, detail="テーブルが存在しません")

    base = config.PUBLIC_BASE_URL.rstrip("/")
    files = []
    for fname in sorted(os.listdir(table_dir)):
        fpath = os.path.join(table_dir, fname)
        if os.path.isfile(fpath):
            files.append(
                {
                    "filename": fname,
                    "size_bytes": os.path.getsize(fpath),
                    "download_url": f"{base}/outputs/{quote(table_name)}/{quote(fname)}",
                }
            )
    return {"table_name": table_name, "files": files}


@app.get("/outputs/{table_name}/{filename}")
async def get_output(table_name: str, filename: str):
    """生成済み成果物を1ファイル返す。Content-Disposition: attachment でダウンロードさせる。"""
    from agent.config import config

    # パストラバーサル対策: サブディレクトリ区切り/親参照を禁止
    for part in (table_name, filename):
        if "/" in part or "\\" in part or part in ("", ".", ".."):
            raise HTTPException(status_code=400, detail="不正なパスです")

    base_dir = os.path.realpath(os.path.join(config.OUTPUT_DIR, "catalog"))
    file_path = os.path.realpath(os.path.join(base_dir, table_name, filename))
    # 解決後パスが base_dir 配下であることを保証
    if not file_path.startswith(base_dir + os.sep):
        raise HTTPException(status_code=400, detail="不正なパスです")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="ファイルが存在しません")

    # filename を渡すと Starlette が Content-Disposition: attachment を付与しダウンロードさせる
    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


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
        from agent.config import config

        base = config.PUBLIC_BASE_URL.rstrip("/")
        lines += ["", "## 生成されたデータカタログ成果物", "", "次のリンクからダウンロードできます。", ""]
        for table, files in catalog.items():
            lines.append(f"### {table}")
            if isinstance(files, dict):
                for key, path in files.items():
                    fname = os.path.basename(str(path))
                    url = f"{base}/outputs/{quote(str(table))}/{quote(fname)}"
                    lines.append(f"- **{key}**: [{fname}]({url})")
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

    result = await _run_analysis(raw, questions, suffix=".csv", filename=filename)
    return json.dumps(_result_to_jsonable(result), ensure_ascii=False)


async def _mcp_call_process_file(arguments: dict) -> str:
    """exapps-proxy mode=mcp_file から呼ばれる。CSV を解析して Markdown サマリを返す。"""
    filename = arguments.get("filename") or "upload.csv"
    content_b64 = (
        arguments.get("content_base64")
        or arguments.get("content")
        or arguments.get("file_content")
    )
    model = arguments.get("model")  # 画面で選択されたモデル（任意）

    if not str(filename).endswith(".csv"):
        raise ValueError("CSV ファイルのみ対応しています (filename must end with .csv)")

    raw = _decode_csv_b64(content_b64)
    result = await _run_analysis(raw, None, suffix=".csv", filename=filename)
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
