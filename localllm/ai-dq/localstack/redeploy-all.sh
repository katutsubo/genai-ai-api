#!/usr/bin/env bash
#
# redeploy-all.sh
# ================
# LocalStack を起動(または再起動)した後に一度だけ実行し、
# ローカルの全 AIアプリ(Lambda + API Gateway)をまとめて再デプロイするスクリプト。
#
# LocalStack(コミュニティ版)は restart / down で Lambda・API Gateway が消えるため、
# 起動のたびに本スクリプトを叩いて復旧する運用を想定している。
#
# 使い方:
#   cd genai-ai-api/localllm/ai-dq/localstack
#   bash redeploy-all.sh
#
# 接続先を変えたい場合(例: genai-local 統合で LiteLLM 経由にする):
#   LMSTUDIO_BASE_URL=http://litellm:4000/v1 LMSTUDIO_API_KEY=sk-localdummy \
#   LMSTUDIO_CHAT_MODEL=chat LMSTUDIO_EMBEDDING_MODEL=embed bash redeploy-all.sh
#
# 新しいアプリを追加したら、末尾の「アプリ定義」配列に1行足すだけでよい。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# ---- 共通設定(環境変数で上書き可) ----
export AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-http://localhost:4566}"
export LMSTUDIO_BASE_URL="${LMSTUDIO_BASE_URL:-http://host.docker.internal:1234/v1}"
export LMSTUDIO_API_KEY="${LMSTUDIO_API_KEY:-lm-studio}"
export LMSTUDIO_CHAT_MODEL="${LMSTUDIO_CHAT_MODEL:-}"
export LMSTUDIO_EMBEDDING_MODEL="${LMSTUDIO_EMBEDDING_MODEL:-}"

# ---- アプリ定義 ----
# 1行 = 1アプリ。書式: "<FUNCTION_NAME>|<API_ID>|<APP_NAME>|<APP_PARAM_FILE>|<DEPLOY_SCRIPT>"
#   FUNCTION_NAME : Lambda 関数名
#   API_ID        : API Gateway の custom id (URL に出る)
#   APP_NAME      : レスポンスフッター等で使うアプリ名
#   APP_PARAM_FILE: config/apps/ 配下の TOML (空文字なら defaults のみ)
#   DEPLOY_SCRIPT : 使用するデプロイスクリプト (空文字なら deploy.sh)
#                   MCP のように別ソース/別ビルドのアプリは deploy-mcp.sh を指定する
APPS=(
  "qe-rag-local|qeragapi|qe-rag-local||deploy.sh"
  "aidq-local|aidqapi|aidq|aidq.toml|deploy.sh"
  "mcp-local|mcpapi|mcp||deploy-mcp.sh"
)

echo "=================================================="
echo " redeploy-all: ${#APPS[@]} app(s)"
echo "   ENDPOINT        : ${AWS_ENDPOINT_URL}"
echo "   LMSTUDIO_BASE_URL: ${LMSTUDIO_BASE_URL}"
echo "=================================================="

for entry in "${APPS[@]}"; do
  IFS='|' read -r fn api app_name app_file deploy_script <<< "${entry}"
  deploy_script="${deploy_script:-deploy.sh}"

  echo
  echo "##################################################"
  echo "# Deploying: ${app_name}  (fn=${fn}, api=${api}, toml=${app_file:-<none>}, script=${deploy_script})"
  echo "##################################################"

  FUNCTION_NAME="${fn}" \
  APP_NAME="${app_name}" \
  APP_PARAM_FILE="${app_file}" \
  bash "${deploy_script}"

  FUNCTION_NAME="${fn}" \
  API_ID="${api}" \
  bash deploy-apigw.sh
done

echo
echo "=================================================="
echo " All apps deployed. Endpoints:"
for entry in "${APPS[@]}"; do
  IFS='|' read -r fn api app_name app_file deploy_script <<< "${entry}"
  echo "   ${app_name}: ${AWS_ENDPOINT_URL}/restapis/${api}/local/_user_request_/"
done
echo "=================================================="
echo
echo "Smoke test (qe-rag):"
echo "  curl -s -XPOST '${AWS_ENDPOINT_URL}/restapis/qeragapi/local/_user_request_/' \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"inputs\":{\"question\":\"テスト\",\"n_queries\":1}}'"
echo
echo "Smoke test (mcp):"
echo "  curl -s -XPOST '${AWS_ENDPOINT_URL}/restapis/mcpapi/local/_user_request_/' \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'"
