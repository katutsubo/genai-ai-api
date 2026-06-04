#!/usr/bin/env bash
#
# MCP サーバ (Model Context Protocol) の Lambda を LocalStack に直接デプロイする。
# mcp-lambda/app.py を単体 zip 化して Lambda 化する。MCP サーバは Python 標準
# ライブラリのみで実装しているため pip install は不要だが、requirements.txt に
# 実依存があればインストールする（将来の依存追加に備える）。
#
# RAG 側 (ai-dq/localstack/deploy.sh) と同様、設定値はすべて環境変数で受け取り、
# スクリプト内にハードコードしない（redeploy-all.sh から値を渡せるようにするため）。
#
# 使い方:
#   (A) スタンドアロン: ホストの LM Studio (host.docker.internal:1234) に接続
#       bash deploy-mcp.sh
#   (B) genai-local 統合: LiteLLM (litellm:4000) 経由
#       LMSTUDIO_BASE_URL=http://litellm:4000/v1 LMSTUDIO_API_KEY=sk-localdummy \
#         bash deploy-mcp.sh
#
# このスクリプトは Lambda 関数のみを作成/更新する。API Gateway での公開は
# 共有スクリプト ../../common/localstack/deploy-apigw.sh が行う:
#   FUNCTION_NAME=mcp-local API_ID=mcpapi bash ../../common/localstack/deploy-apigw.sh
#
# 前提:
#   - aws CLI (AWS_ENDPOINT_URL 指定) または awslocal
#   - python3 / pip(任意), zip

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMBDA_SRC="${SCRIPT_DIR}/mcp-lambda"
BUILD_DIR="${SCRIPT_DIR}/.build-mcp"
ZIP_FILE="${SCRIPT_DIR}/mcp-function.zip"

FUNCTION_NAME="${FUNCTION_NAME:-mcp-local}"
LAMBDA_TIMEOUT="${LAMBDA_TIMEOUT:-60}"
LAMBDA_MEMORY="${LAMBDA_MEMORY:-512}"

# LocalStack エンドポイント: AWS_ENDPOINT_URL > LOCALSTACK_ENDPOINT > localhost:4566
ENDPOINT="${AWS_ENDPOINT_URL:-${LOCALSTACK_ENDPOINT:-http://localhost:4566}}"

# list_models ツールが叩く OpenAI 互換エンドポイント (Lambda コンテナ内から見たホスト名)
#  - スタンドアロン既定: http://host.docker.internal:1234/v1 (ホストの LM Studio)
#  - genai-local 統合時 : http://litellm:4000/v1 を渡す
LMSTUDIO_BASE_URL="${LMSTUDIO_BASE_URL:-http://host.docker.internal:1234/v1}"
LMSTUDIO_API_KEY="${LMSTUDIO_API_KEY:-lm-studio}"
LMSTUDIO_TIMEOUT="${LMSTUDIO_TIMEOUT:-15}"
MCP_SERVER_NAME="${MCP_SERVER_NAME:-localstack-mcp}"
MCP_FILE_PREVIEW_CHARS="${MCP_FILE_PREVIEW_CHARS:-2000}"
LOG_LEVEL="${LOG_LEVEL:-DEBUG}"

# pip の選択 (RAG deploy.sh と同様。MCP は依存ゼロなので無くても可)
if [ -n "${PIP:-}" ]; then
  : # ユーザ指定をそのまま使う
elif command -v pip >/dev/null 2>&1; then
  PIP="pip"
elif command -v pip3 >/dev/null 2>&1; then
  PIP="pip3"
elif command -v python3 >/dev/null 2>&1; then
  PIP="python3 -m pip"
elif command -v python >/dev/null 2>&1; then
  PIP="python -m pip"
else
  PIP=""
fi

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

echo "[2/5] Copying source (and installing deps if any)..."
# requirements.txt に実依存(コメント/空行以外)があればインストールする。
# MCP は標準ライブラリのみのため、通常はスキップされる。
if [ -n "${PIP}" ] && [ -f "${LAMBDA_SRC}/requirements.txt" ] \
   && grep -qvE '^[[:space:]]*(#.*)?$' "${LAMBDA_SRC}/requirements.txt"; then
  echo "      using PIP='${PIP}'"
  ${PIP} install -r "${LAMBDA_SRC}/requirements.txt" -t "${BUILD_DIR}" --quiet
fi
# ソースを配置 (テストコードは同梱しない)
cp -a "${LAMBDA_SRC}/app.py" "${BUILD_DIR}/"
if [ -f "${LAMBDA_SRC}/requirements.txt" ]; then
  cp -a "${LAMBDA_SRC}/requirements.txt" "${BUILD_DIR}/"
fi

echo "[3/5] Zipping..."
(cd "${BUILD_DIR}" && zip -qr "${ZIP_FILE}" .)

echo "[4/5] Creating/updating Lambda function '${FUNCTION_NAME}' (timeout=${LAMBDA_TIMEOUT}s)..."
echo "      LMSTUDIO_BASE_URL='${LMSTUDIO_BASE_URL}'"

# --environment は JSON 形式で渡す (空文字の値があってもパーサが落ちないように)。
ENV_JSON=$(cat <<EOF
{"Variables":{"LMSTUDIO_BASE_URL":"${LMSTUDIO_BASE_URL}","LMSTUDIO_API_KEY":"${LMSTUDIO_API_KEY}","LMSTUDIO_TIMEOUT":"${LMSTUDIO_TIMEOUT}","MCP_SERVER_NAME":"${MCP_SERVER_NAME}","MCP_FILE_PREVIEW_CHARS":"${MCP_FILE_PREVIEW_CHARS}","LOG_LEVEL":"${LOG_LEVEL}"}}
EOF
)

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
echo "Next: publish via API Gateway (custom id 'mcpapi'):"
echo "  FUNCTION_NAME=${FUNCTION_NAME} API_ID=mcpapi bash ../../common/localstack/deploy-apigw.sh"
echo "Try (tools/list):"
echo "  curl -s -XPOST '${ENDPOINT}/restapis/mcpapi/local/_user_request_/' \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'"
