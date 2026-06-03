#!/usr/bin/env bash
#
# デプロイ済み Lambda を lambda invoke で直接呼び出すサンプル (共有スクリプト)。
# event ファイル (API Gateway proxy 形式) を送り、レスポンスを表示する。
#
# 第1引数で event ファイルを渡せる (未指定時はカレントの event.sample.json)。
#   RAG : FUNCTION_NAME=qe-rag-local bash ../../common/localstack/invoke.sh ../../ai-dq/localstack/event.sample.json
#   MCP : FUNCTION_NAME=mcp-local    bash ../../common/localstack/invoke.sh ../../ai-dq-mcp/localstack/event.mcp.sample.json
#
# ローカルLLMは推論に時間がかかるため、CLI の読み取りタイムアウトを
# CLI_READ_TIMEOUT (既定 900秒) まで伸ばしている。

set -euo pipefail

FUNCTION_NAME="${FUNCTION_NAME:-qe-rag-local}"
ENDPOINT="${AWS_ENDPOINT_URL:-${LOCALSTACK_ENDPOINT:-http://localhost:4566}}"
EVENT_FILE="${1:-./event.sample.json}"
OUT_FILE="${OUT_FILE:-./response.json}"
CLI_READ_TIMEOUT="${CLI_READ_TIMEOUT:-900}"

if [ ! -f "${EVENT_FILE}" ]; then
  echo "error: event file not found: ${EVENT_FILE}" >&2
  echo "usage: FUNCTION_NAME=<fn> bash invoke.sh <event-json-path>" >&2
  exit 2
fi

if [ -n "${AWS_ENDPOINT_URL:-}" ]; then
  AWS="aws --endpoint-url=${AWS_ENDPOINT_URL}"
elif command -v awslocal >/dev/null 2>&1; then
  AWS="awslocal"
else
  AWS="aws --endpoint-url=${ENDPOINT}"
fi

# Active になるまで待つ (Pending 中の ResourceConflictException を回避)
${AWS} lambda wait function-active-v2 --function-name "${FUNCTION_NAME}" 2>/dev/null \
  || ${AWS} lambda wait function-active --function-name "${FUNCTION_NAME}" 2>/dev/null \
  || true

echo "Invoking ${FUNCTION_NAME} with ${EVENT_FILE} (read-timeout=${CLI_READ_TIMEOUT}s) ..."
${AWS} --cli-read-timeout "${CLI_READ_TIMEOUT}" --cli-connect-timeout 10 \
  lambda invoke \
  --function-name "${FUNCTION_NAME}" \
  --payload "fileb://${EVENT_FILE}" \
  --cli-binary-format raw-in-base64-out \
  "${OUT_FILE}" >/dev/null

echo "--- Raw Lambda response (${OUT_FILE}) ---"
cat "${OUT_FILE}"
echo
echo "--- Parsed body ---"
python3 -c "import json,sys; r=json.load(open('${OUT_FILE}')); b=r.get('body'); print(json.dumps(json.loads(b), ensure_ascii=False, indent=2) if b else r)" 2>/dev/null || true
