#!/usr/bin/env bash
#
# query-expansion-rag の Lambda を LocalStack に直接デプロイするスクリプト。
# API Gateway / WAF / KMS / OpenSearch は使わず、Lambda 単体を作成する。
#
# 2つの使い方に対応:
#   (A) スタンドアロン: 本ディレクトリの docker-compose.yml で LocalStack を起動し、
#       ホストの LMStudio (host.docker.internal:1234) に接続する。
#   (B) genai-local 統合: 既存の docker-compose.yaml (genai-net) の LocalStack に対し、
#       LiteLLM (litellm:4000) 経由で LM Studio に接続する。
#       例: LMSTUDIO_BASE_URL=http://litellm:4000/v1 LMSTUDIO_API_KEY=sk-localdummy \
#            LMSTUDIO_CHAT_MODEL=chat LMSTUDIO_EMBEDDING_MODEL=embed ./deploy.sh
#
# 前提:
#   - docker / docker compose
#   - awslocal (pip install awscli-local) または aws --endpoint-url=http://localhost:4566
#   - python3, pip, zip

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMBDA_SRC="$(cd "${SCRIPT_DIR}/../lib/constructs/rag-lambda/invokeModel" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/.build"
ZIP_FILE="${SCRIPT_DIR}/function.zip"

FUNCTION_NAME="${FUNCTION_NAME:-qe-rag-local}"
AWS_REGION_LOCAL="${AWS_REGION_LOCAL:-ap-northeast-1}"
LAMBDA_TIMEOUT="${LAMBDA_TIMEOUT:-900}"
LAMBDA_MEMORY="${LAMBDA_MEMORY:-512}"

# LocalStack エンドポイント: AWS_ENDPOINT_URL > LOCALSTACK_ENDPOINT > localhost:4566
ENDPOINT="${AWS_ENDPOINT_URL:-${LOCALSTACK_ENDPOINT:-http://localhost:4566}}"

# LMStudio / LiteLLM 接続先 (Lambda コンテナ内から見たホスト名)
#  - スタンドアロン既定: http://host.docker.internal:1234/v1 (ホストの LM Studio)
#  - genai-local 統合時: http://litellm:4000/v1 を指定する
LMSTUDIO_BASE_URL="${LMSTUDIO_BASE_URL:-http://host.docker.internal:1234/v1}"
LMSTUDIO_API_KEY="${LMSTUDIO_API_KEY:-lm-studio}"
LMSTUDIO_CHAT_MODEL="${LMSTUDIO_CHAT_MODEL:-}"
LMSTUDIO_EMBEDDING_MODEL="${LMSTUDIO_EMBEDDING_MODEL:-}"

# AWS CLI の選択:
#  - AWS_ENDPOINT_URL が明示されていればそれを使う (コンテナ内 genai-net 等)
#  - それ以外は awslocal があれば awslocal、無ければ aws --endpoint-url
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

echo "[3/5] Zipping..."
(cd "${BUILD_DIR}" && zip -qr "${ZIP_FILE}" .)

echo "[4/5] Creating/updating Lambda function '${FUNCTION_NAME}' (timeout=${LAMBDA_TIMEOUT}s)..."
ENV_VARS="Variables={USE_LOCAL_LLM=true,LMSTUDIO_BASE_URL=${LMSTUDIO_BASE_URL},LMSTUDIO_API_KEY=${LMSTUDIO_API_KEY},LMSTUDIO_CHAT_MODEL=${LMSTUDIO_CHAT_MODEL},LMSTUDIO_EMBEDDING_MODEL=${LMSTUDIO_EMBEDDING_MODEL},KNOWLEDGE_BASE_ID=local-dummy-kb,KB_NUM_RESULTS=5,APP_NAME=qe-rag-local,APP_PARAM_FILE=,LOG_LEVEL=DEBUG,AWS_ACCOUNT_ID=000000000000}"

if ${AWS} lambda get-function --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  ${AWS} lambda update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file "fileb://${ZIP_FILE}" >/dev/null
  # コード更新が反映されるまで待つ
  ${AWS} lambda wait function-updated --function-name "${FUNCTION_NAME}" 2>/dev/null || sleep 5
  ${AWS} lambda update-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --timeout "${LAMBDA_TIMEOUT}" \
    --memory-size "${LAMBDA_MEMORY}" \
    --environment "${ENV_VARS}" >/dev/null
else
  ${AWS} lambda create-function \
    --function-name "${FUNCTION_NAME}" \
    --runtime python3.12 \
    --handler app.handler \
    --timeout "${LAMBDA_TIMEOUT}" \
    --memory-size "${LAMBDA_MEMORY}" \
    --role arn:aws:iam::000000000000:role/lambda-role \
    --environment "${ENV_VARS}" \
    --zip-file "fileb://${ZIP_FILE}" >/dev/null
fi

echo "[5/5] Waiting for function to become Active..."
${AWS} lambda wait function-active-v2 --function-name "${FUNCTION_NAME}" 2>/dev/null \
  || ${AWS} lambda wait function-active --function-name "${FUNCTION_NAME}" 2>/dev/null \
  || sleep 5

echo "Done. Deployed Lambda: ${FUNCTION_NAME}"
echo "  Endpoint     : ${ENDPOINT}"
echo "  LMSTUDIO_BASE_URL: ${LMSTUDIO_BASE_URL}"
echo "Try: ./invoke.sh"
