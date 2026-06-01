#!/usr/bin/env bash
#
# デプロイ済み Lambda を awslocal lambda invoke で直接呼び出すサンプル。
# event.sample.json (API Gateway proxy 形式) を送り、レスポンスを表示する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUNCTION_NAME="${FUNCTION_NAME:-qe-rag-local}"
ENDPOINT="${LOCALSTACK_ENDPOINT:-http://localhost:4566}"
EVENT_FILE="${1:-${SCRIPT_DIR}/event.sample.json}"
OUT_FILE="${SCRIPT_DIR}/response.json"

if command -v awslocal >/dev/null 2>&1; then
  AWS="awslocal"
else
  AWS="aws --endpoint-url=${ENDPOINT}"
fi

echo "Invoking ${FUNCTION_NAME} with ${EVENT_FILE} ..."
${AWS} lambda invoke \
  --function-name "${FUNCTION_NAME}" \
  --payload "fileb://${EVENT_FILE}" \
  --cli-binary-format raw-in-base64-out \
  "${OUT_FILE}" >/dev/null

echo "--- Raw Lambda response (${OUT_FILE}) ---"
cat "${OUT_FILE}"
echo
echo "--- Parsed body ---"
python3 -c "import json,sys; r=json.load(open('${OUT_FILE}')); b=r.get('body'); print(json.dumps(json.loads(b), ensure_ascii=False, indent=2) if b else r)" 2>/dev/null || true
