#!/usr/bin/env bash
#
# ローカルファイルを base64 化して MCP サーバの process_file ツールに投げ、
# 解析結果 (要約) を表示するサンプルスクリプト。
#
# MCP は API Gateway (REST, proxy 統合) 経由で HTTP 公開されている前提:
#   API_ID=mcpapi FUNCTION_NAME=mcp-local bash ../../common/localstack/deploy-apigw.sh
#
# 使い方:
#   cd localllm/ai-dq-mcp/localstack
#   bash invoke-mcp-file.sh <ファイルパス>
#   # 例:
#   bash invoke-mcp-file.sh ../../ai-dq/localstack/local_kb_docs.json
#
#   # genai-net 内コンテナから / エンドポイントや API ID を変える場合:
#   AWS_ENDPOINT_URL=http://localstack:4566 API_ID=mcpapi \
#     bash invoke-mcp-file.sh ./some.txt
#
# ※ 本スクリプトは API_ID / STAGE / AWS_ENDPOINT_URL を「環境変数」で受け取る設計です。
#   値をスクリプト内にハードコードしないこと (既存スクリプトと同じ規約)。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

FILE_PATH="${1:-}"
if [ -z "${FILE_PATH}" ]; then
  echo "usage: bash invoke-mcp-file.sh <file-path>" >&2
  exit 2
fi
if [ ! -f "${FILE_PATH}" ]; then
  echo "error: file not found: ${FILE_PATH}" >&2
  exit 2
fi

ENDPOINT="${AWS_ENDPOINT_URL:-${LOCALSTACK_ENDPOINT:-http://localhost:4566}}"
API_ID="${API_ID:-mcpapi}"
STAGE="${STAGE:-local}"
CONTENT_TYPE="${CONTENT_TYPE:-application/octet-stream}"
URL="${ENDPOINT}/restapis/${API_ID}/${STAGE}/_user_request_/"

FILENAME="$(basename "${FILE_PATH}")"

# base64 (改行なし) を生成。GNU/BSD どちらの base64 でも動くようにする。
if base64 --help 2>&1 | grep -q -- "-w"; then
  CONTENT_B64="$(base64 -w0 "${FILE_PATH}")"
else
  CONTENT_B64="$(base64 "${FILE_PATH}" | tr -d '\n')"
fi

# JSON-RPC body を Python で安全に組み立てる (base64 をそのまま埋め込むとエスケープが面倒なため)
BODY=$(FILENAME="${FILENAME}" CONTENT_B64="${CONTENT_B64}" CONTENT_TYPE="${CONTENT_TYPE}" \
  python3 -c 'import json, os; print(json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"process_file","arguments":{"filename":os.environ["FILENAME"],"content_base64":os.environ["CONTENT_B64"],"content_type":os.environ["CONTENT_TYPE"]}}}))')

echo "POST ${URL}"
echo "  file     : ${FILE_PATH}"
echo "  filename : ${FILENAME}"
echo

RESPONSE=$(curl -s -XPOST "${URL}" -H 'Content-Type: application/json' -d "${BODY}")

echo "--- Raw response ---"
echo "${RESPONSE}"
echo
echo "--- process_file summary ---"
echo "${RESPONSE}" | python3 -c 'import json,sys; r=json.load(sys.stdin); c=r.get("result",{}).get("content"); print(json.dumps(json.loads(c[0]["text"]), ensure_ascii=False, indent=2) if c else r)'
