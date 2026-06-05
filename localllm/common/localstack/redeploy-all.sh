#!/usr/bin/env bash
#
# redeploy-all.sh (共有・統合版)
# ==============================
# LocalStack を起動(または再起動)した後に一度だけ実行し、
# ローカルの全 AIアプリ(Lambda + API Gateway)をまとめて再デプロイするスクリプト。
#
# LocalStack(コミュニティ版)は restart / down で Lambda・API Gateway が消えるため、
# 起動のたびに本スクリプトを叩いて復旧する運用を想定している。
#
# ディレクトリ構成 (3アプリ ↔ ディレクトリ):
#   localllm/query-expansion-rag        … (qeragapi / qe-rag-local) ※将来分離する場合
#   localllm/ai-dq/localstack           … RAG  (aidqapi / aidq-local)   deploy.sh
#   localllm/ai-dq-mcp/localstack       … MCP  (mcpapi  / mcp-local)    deploy-mcp.sh
#   localllm/common/localstack          … 共有 (deploy-apigw.sh / invoke.sh / 本スクリプト)
#
# 常駐コンテナ (Lambda ではない):
#   localllm/catalog-agent              … データ品質＆カタログ MCP サーバ
#                                         (A7C3E2D1 アプリが http://catalog-agent:8002/mcp を使う)
#   → LocalStack とは無関係に docker compose の常駐コンテナとして起動する必要がある。
#     本スクリプトの末尾で `docker compose up -d catalog-agent` を実行する。
#
# アプリ画面定義(exapps-proxy 用):
#   各アプリの exapp.json を build-apps-json.sh が localllm/apps.generated.json に集約する。
#   本スクリプトの先頭で自動実行する。
#
# 使い方:
#   cd localllm/common/localstack
#   bash redeploy-all.sh
#
# 接続先を変えたい場合(例: genai-local 統合で LiteLLM 経由にする):
#   LMSTUDIO_BASE_URL=http://litellm:4000/v1 LMSTUDIO_API_KEY=sk-localdummy \
#   LMSTUDIO_CHAT_MODEL=chat LMSTUDIO_EMBEDDING_MODEL=embed bash redeploy-all.sh
#
# catalog-agent の自動起動を抑止したい場合:
#   SKIP_CATALOG_AGENT=1 bash redeploy-all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# localllm/ 直下 (common/localstack の2つ上)
LOCALLLM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# genai-local ルート (compose のある場所)。
# 構成: genai-local/genai-ai-api/localllm/common/localstack → 4つ上が genai-local。
# genai-ai-api を単体 clone している場合は存在しないため、後段で compose の有無を確認する。
GENAI_LOCAL_ROOT="$(cd "${SCRIPT_DIR}/../../../.." 2>/dev/null && pwd || true)"

AIDQ_LS="${LOCALLLM_DIR}/ai-dq/localstack"
MCP_LS="${LOCALLLM_DIR}/ai-dq-mcp/localstack"
APIGW="${SCRIPT_DIR}/deploy-apigw.sh"
BUILD_APPS="${SCRIPT_DIR}/build-apps-json.sh"

# ---- 共通設定(環境変数で上書き可) ----
export AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-http://localhost:4566}"
export LMSTUDIO_BASE_URL="${LMSTUDIO_BASE_URL:-http://litellm:4000/v1}"
export LMSTUDIO_API_KEY="${LMSTUDIO_API_KEY:-sk-localdummy}"
export LMSTUDIO_CHAT_MODEL="${LMSTUDIO_CHAT_MODEL:-chat}"
export LMSTUDIO_EMBEDDING_MODEL="${LMSTUDIO_EMBEDDING_MODEL:-embed}"

# ---- exapps-proxy 用 apps.generated.json を生成 ----
# 各アプリの localllm/<app>/exapp.json を集約する。jq が無い等で失敗しても
# Lambda デプロイ自体は続行する(画面定義は既存の生成物を使う)。
if [ -f "${BUILD_APPS}" ]; then
  echo
  echo "[apps] generating apps.generated.json from localllm/*/exapp.json ..."
  bash "${BUILD_APPS}" || echo "  (warning) apps.generated.json の生成に失敗しました(既存ファイルを使用)"
fi

echo "=================================================="
echo " redeploy-all (split layout)"
echo "   ENDPOINT        : ${AWS_ENDPOINT_URL}"
echo "   LMSTUDIO_BASE_URL: ${LMSTUDIO_BASE_URL}"
echo "   ai-dq    (RAG)  : ${AIDQ_LS}"
echo "   ai-dq-mcp(MCP)  : ${MCP_LS}"
echo "=================================================="

# ---- RAG 系 (ai-dq/localstack の deploy.sh) ----
# 1行 = 1アプリ。書式: "<FUNCTION_NAME>|<API_ID>|<APP_NAME>|<APP_PARAM_FILE>"
RAG_APPS=(
  "qe-rag-local|qeragapi|qe-rag-local|"
  "aidq-local|aidqapi|aidq|aidq.toml"
)

for entry in "${RAG_APPS[@]}"; do
  IFS='|' read -r fn api app_name app_file <<< "${entry}"
  echo
  echo "##################################################"
  echo "# [RAG] Deploying: ${app_name} (fn=${fn}, api=${api}, toml=${app_file:-<none>})"
  echo "##################################################"
  (
    cd "${AIDQ_LS}"
    FUNCTION_NAME="${fn}" APP_NAME="${app_name}" APP_PARAM_FILE="${app_file}" \
      bash ./deploy.sh
    FUNCTION_NAME="${fn}" API_ID="${api}" bash "${APIGW}"
  )
done

# ---- MCP 系 (ai-dq-mcp/localstack の deploy-mcp.sh) ----
echo
echo "##################################################"
echo "# [MCP] Deploying: mcp (fn=mcp-local, api=mcpapi)"
echo "##################################################"
(
  cd "${MCP_LS}"
  FUNCTION_NAME="mcp-local" bash ./deploy-mcp.sh
  FUNCTION_NAME="mcp-local" API_ID="mcpapi" bash "${APIGW}"
)

# ---- 常駐コンテナ catalog-agent を起動 ----
# catalog-agent は Lambda ではなく docker compose の常駐コンテナ。
# LocalStack を上げ直しても消えないが、スタックを停止していると未起動のままになり、
# A7C3E2D1(データ品質＆カタログ)アプリが CORSエラー / Failed to fetch で落ちる。
# ここで明示的に起動して「起動し忘れ」を防ぐ。
# (SKIP_CATALOG_AGENT=1 で抑止可能。docker / compose 不在や単体 clone でも安全にスキップする。)
echo
echo "##################################################"
echo "# [catalog-agent] Starting 常駐コンテナ"
echo "##################################################"
if [ "${SKIP_CATALOG_AGENT:-0}" = "1" ]; then
  echo "  SKIP_CATALOG_AGENT=1 のためスキップします。"
elif ! command -v docker >/dev/null 2>&1; then
  echo "  (skip) docker が見つかりません。手動で 'docker compose up -d catalog-agent' を実行してください。"
elif [ -z "${GENAI_LOCAL_ROOT}" ] || [ ! -f "${GENAI_LOCAL_ROOT}/docker-compose.yaml" ]; then
  echo "  (skip) genai-local の docker-compose.yaml が見つかりません(単体 clone 等)。"
  echo "         genai-local ルートで 'docker compose up -d catalog-agent' を実行してください。"
else
  if (cd "${GENAI_LOCAL_ROOT}" && docker compose up -d catalog-agent); then
    echo "  catalog-agent を起動しました (http://catalog-agent:8002/mcp)。"
  else
    echo "  (warning) catalog-agent の起動に失敗しました。" >&2
    echo "            genai-local ルートで 'docker compose up -d catalog-agent' を手動実行してください。" >&2
  fi
fi

echo
echo "=================================================="
echo " All apps deployed. Endpoints:"
echo "   qe-rag-local : ${AWS_ENDPOINT_URL}/restapis/qeragapi/local/_user_request_/"
echo "   aidq-local   : ${AWS_ENDPOINT_URL}/restapis/aidqapi/local/_user_request_/"
echo "   mcp-local    : ${AWS_ENDPOINT_URL}/restapis/mcpapi/local/_user_request_/"
echo "   catalog-agent: http://catalog-agent:8002/mcp (常駐コンテナ / genai-net 内)"
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
echo
echo "Smoke test (catalog-agent):"
echo "  curl -s http://localhost:8002/health"
echo "  curl -s -XPOST http://localhost:8002/mcp \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'"
