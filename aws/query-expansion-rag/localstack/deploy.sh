#!/usr/bin/env bash
#
# query-expansion-rag の Lambda を LocalStack に直接デプロイするスクリプト。
# API Gateway / WAF / KMS / OpenSearch は使わず、Lambda 単体を作成する。
#
# 前提:
#   - docker / docker compose
#   - awslocal (pip install awscli-local) または aws --endpoint-url=http://localhost:4566
#   - python3, pip
#   - LMStudio がホストで OpenAI互換サーバーを起動済み (既定ポート 1234)
#
# 使い方:
#   cd aws/query-expansion-rag/localstack
#   docker compose up -d
#   ./deploy.sh
#   ./invoke.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMBDA_SRC="$(cd "${SCRIPT_DIR}/../lib/constructs/rag-lambda/invokeModel" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/.build"
ZIP_FILE="${SCRIPT_DIR}/function.zip"

FUNCTION_NAME="${FUNCTION_NAME:-qe-rag-local}"
AWS_REGION_LOCAL="${AWS_REGION_LOCAL:-ap-northeast-1}"
ENDPOINT="${LOCALSTACK_ENDPOINT:-http://localhost:4566}"

# LMStudio 接続先 (Lambda コンテナ内から見たホスト)
LMSTUDIO_BASE_URL="${LMSTUDIO_BASE_URL:-http://host.docker.internal:1234/v1}"
LMSTUDIO_API_KEY="${LMSTUDIO_API_KEY:-lm-studio}"
LMSTUDIO_CHAT_MODEL="${LMSTUDIO_CHAT_MODEL:-}"
LMSTUDIO_EMBEDDING_MODEL="${LMSTUDIO_EMBEDDING_MODEL:-}"

# awslocal があればそれを、無ければ aws --endpoint-url を使う
if command -v awslocal >/dev/null 2>&1; then
  AWS="awslocal"
else
  AWS="aws --endpoint-url=${ENDPOINT}"
fi

echo "[1/4] Cleaning build dir..."
rm -rf "${BUILD_DIR}" "${ZIP_FILE}"
mkdir -p "${BUILD_DIR}"

echo "[2/4] Installing dependencies and copying source..."
pip install -r "${LAMBDA_SRC}/requirements.txt" -t "${BUILD_DIR}" --quiet
cp -a "${LAMBDA_SRC}/." "${BUILD_DIR}/"

# config/defaults と config/apps を同梱 (本番ビルドと同様の配置)
mkdir -p "${BUILD_DIR}/config/defaults" "${BUILD_DIR}/config/apps"
cp -r "${SCRIPT_DIR}/../config/defaults/." "${BUILD_DIR}/config/defaults/"
if [ -d "${SCRIPT_DIR}/../config/apps" ]; then
  cp -r "${SCRIPT_DIR}/../config/apps/." "${BUILD_DIR}/config/apps/" 2>/dev/null || true
fi

# ローカルKB用のサンプルドキュメントがあれば同梱
if [ -f "${SCRIPT_DIR}/local_kb_docs.json" ]; then
  cp "${SCRIPT_DIR}/local_kb_docs.json" "${BUILD_DIR}/local_kb_docs.json"
fi

echo "[3/4] Zipping..."
(cd "${BUILD_DIR}" && zip -qr "${ZIP_FILE}" .)

echo "[4/4] Creating/updating Lambda function '${FUNCTION_NAME}'..."
ENV_VARS="Variables={USE_LOCAL_LLM=true,LMSTUDIO_BASE_URL=${LMSTUDIO_BASE_URL},LMSTUDIO_API_KEY=${LMSTUDIO_API_KEY},LMSTUDIO_CHAT_MODEL=${LMSTUDIO_CHAT_MODEL},LMSTUDIO_EMBEDDING_MODEL=${LMSTUDIO_EMBEDDING_MODEL},KNOWLEDGE_BASE_ID=local-dummy-kb,KB_NUM_RESULTS=5,APP_NAME=qe-rag-local,APP_PARAM_FILE=,LOG_LEVEL=DEBUG,AWS_ACCOUNT_ID=000000000000}"

if ${AWS} lambda get-function --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  ${AWS} lambda update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file "fileb://${ZIP_FILE}" >/dev/null
  ${AWS} lambda update-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --environment "${ENV_VARS}" >/dev/null
else
  ${AWS} lambda create-function \
    --function-name "${FUNCTION_NAME}" \
    --runtime python3.12 \
    --handler app.handler \
    --timeout 180 \
    --memory-size 512 \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --environment "${ENV_VARS}" \
    --zip-file "fileb://${ZIP_FILE}" >/dev/null
fi

echo "Done. Deployed Lambda: ${FUNCTION_NAME}"
echo "Try: ./invoke.sh"
