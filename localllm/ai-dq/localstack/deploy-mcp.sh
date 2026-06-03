#!/usr/bin/env bash
#
# MCP (Model Context Protocol) サーバ用 Lambda を LocalStack に直接デプロイする。
# 既存の deploy.sh と同じ規約に揃えている:
#   - 関数名等は「環境変数」で受け取り、スクリプト内にハードコードしない
#   - AWS CLI 選択ロジック (AWS_ENDPOINT_URL > awslocal > aws --endpoint-url)
#   - ランタイム python3.12 / ハンドラ app.handler
#   - --environment は JSON 形式で渡す (空文字の値でも壊れないように)
#
# 使い方 (docker compose up -d の後):
#   bash deploy-mcp.sh
#   FUNCTION_NAME=mcp-local bash deploy-mcp.sh
#   # genai-net 内コンテナから:
#   AWS_ENDPOINT_URL=http://localstack:4566 FUNCTION_NAME=mcp-local bash deploy-mcp.sh
#
# その後 deploy-apigw.sh で HTTP 公開する:
#   API_ID=mcpapi FUNCTION_NAME=mcp-local bash deploy-apigw.sh
#
# ※ MCP の Lambda ソースは RAG (lib/constructs/rag-lambda/invokeModel) とは別の
#   mcp-lambda/ に置く。LAMBDA_SRC 環境変数で上書きも可能。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMBDA_SRC="${LAMBDA_SRC:-${SCRIPT_DIR}/mcp-lambda}"
BUILD_DIR="${SCRIPT_DIR}/.build-mcp"
ZIP_FILE="${SCRIPT_DIR}/function-mcp.zip"

FUNCTION_NAME="${FUNCTION_NAME:-mcp-local}"
AWS_REGION_LOCAL="${AWS_REGION_LOCAL:-ap-northeast-1}"
LAMBDA_TIMEOUT="${LAMBDA_TIMEOUT:-30}"
LAMBDA_MEMORY="${LAMBDA_MEMORY:-256}"

# LocalStack エンドポイント: AWS_ENDPOINT_URL > LOCALSTACK_ENDPOINT > localhost:4566
ENDPOINT="${AWS_ENDPOINT_URL:-${LOCALSTACK_ENDPOINT:-http://localhost:4566}}"

# list_models ツールが叩く LMStudio/LiteLLM 接続先 (Lambda コンテナ内から見たホスト名)
LMSTUDIO_BASE_URL="${LMSTUDIO_BASE_URL:-http://host.docker.internal:1234/v1}"
LMSTUDIO_API_KEY="${LMSTUDIO_API_KEY:-lm-studio}"

MCP_SERVER_NAME="${MCP_SERVER_NAME:-localstack-mcp}"
MCP_SERVER_VERSION="${MCP_SERVER_VERSION:-0.1.0}"

# AWS CLI の選択
if [ -n "${AWS_ENDPOINT_URL:-}" ]; then
  AWS="aws --endpoint-url=${AWS_ENDPOINT_URL}"
elif command -v awslocal >/dev/null 2>&1; then
  AWS="awslocal"
else
  AWS="aws --endpoint-url=${ENDPOINT}"
fi

echo "[1/5] Cleaning build dir..."
rm -rf "${BUILD_DIR}" "${ZIP_FILE}"
mkdir -p "${BUILD_DIR}"

echo "[2/5] Installing dependencies and copying source..."
if [ -f "${LAMBDA_SRC}/requirements.txt" ]; then
  # 依存が空でも pip install は成功する
  pip install -r "${LAMBDA_SRC}/requirements.txt" -t "${BUILD_DIR}" --quiet || true
fi
cp -a "${LAMBDA_SRC}/." "${BUILD_DIR}/"
# テストはパッケージに含めない
rm -f "${BUILD_DIR}/test_app.py"

echo "[3/5] Zipping..."
(cd "${BUILD_DIR}" && zip -qr "${ZIP_FILE}" .)

echo "[4/5] Creating/updating Lambda function '${FUNCTION_NAME}' (timeout=${LAMBDA_TIMEOUT}s)..."

# --environment は JSON 形式で渡す (空文字の値でも安全)
ENV_JSON=$(cat <<EOF
{"Variables":{"LMSTUDIO_BASE_URL":"${LMSTUDIO_BASE_URL}","LMSTUDIO_API_KEY":"${LMSTUDIO_API_KEY}","MCP_SERVER_NAME":"${MCP_SERVER_NAME}","MCP_SERVER_VERSION":"${MCP_SERVER_VERSION}"}}
EOF
)

if ${AWS} lambda get-function --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  ${AWS} lambda update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file "fileb://${ZIP_FILE}" >/dev/null
  ${AWS} lambda wait function-updated --function-name "${FUNCTION_NAME}" 2>/dev/null || sleep 5
  ${AWS} lambda update-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --timeout "${LAMBDA_TIMEOUT}" \
    --memory-size "${LAMBDA_MEMORY}" \
    --environment "${ENV_JSON}" >/dev/null
else
  ${AWS} lambda create-function \
    --function-name "${FUNCTION_NAME}" \
    --runtime python3.12 \
    --handler app.handler \
    --timeout "${LAMBDA_TIMEOUT}" \
    --memory-size "${LAMBDA_MEMORY}" \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --environment "${ENV_JSON}" \
    --zip-file "fileb://${ZIP_FILE}" >/dev/null
fi

echo "[5/5] Waiting for function to become Active..."
${AWS} lambda wait function-active-v2 --function-name "${FUNCTION_NAME}" 2>/dev/null \
  || ${AWS} lambda wait function-active --function-name "${FUNCTION_NAME}" 2>/dev/null \
  || sleep 5

echo "Done. Deployed MCP Lambda: ${FUNCTION_NAME}"
echo "  Endpoint        : ${ENDPOINT}"
echo "  LMSTUDIO_BASE_URL: ${LMSTUDIO_BASE_URL}"
echo "Next: API_ID=mcpapi FUNCTION_NAME=${FUNCTION_NAME} bash deploy-apigw.sh"
