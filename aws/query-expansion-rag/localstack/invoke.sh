#!/usr/bin/env bash
#
# デプロイ済み Lambda を lambda invoke で直接呼び出すサンプル。
# event.sample.json (API Gateway proxy 形式) を送り、レスポンスを表示する。
#
# ローカルLLMは推論に時間がかかるため、CLI の読み取りタイムアウトを
# CLI_READ_TIMEOUT (既定 900秒) まで伸ばしている。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUNCTION_NAME="${FUNCTION_NAME:-qe-rag-local}"
ENDPOINT="${AWS_ENDPOINT_URL:-${LOCALSTACK_ENDPOINT:-http://localhost:4566}}"
EVENT_FILE="${1:-${SCRIPT_DIR}/event.sample.json}"
OUT_FILE="${SCRIPT_DIR}/response.json"
CLI_READ_TIMEOUT="${CLI_READ_TIMEOUT:-900}"

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
