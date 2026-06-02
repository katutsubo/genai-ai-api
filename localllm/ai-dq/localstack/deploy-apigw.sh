#!/usr/bin/env bash
#
# qe-rag-local / aidq-local など Lambda を REST API (proxy統合) として HTTP 公開する。
# genai-web などの HTTP クライアントから叩けるようにする。
#
# LocalStack の custom id 機能 (_custom_id_ タグ) で安定した API ID を付与するため、
# 再デプロイしても URL が変わらない。
#
# 公開される URL:
#   http://localhost:4566/restapis/<API_ID>/<STAGE>/_user_request_/
#
# 使い方 (deploy.sh の後に実行):
#   API_ID=qeragapi FUNCTION_NAME=qe-rag-local bash deploy-apigw.sh
#   # genai-net 内コンテナから実行する場合:
#   AWS_ENDPOINT_URL=http://localstack:4566 API_ID=qeragapi FUNCTION_NAME=qe-rag-local bash deploy-apigw.sh
#
# ※ 注意: 本スクリプトは API_ID / FUNCTION_NAME を「環境変数」で受け取る設計です。
#   スクリプト内に値をハードコードしないこと。ハードコードすると redeploy-all.sh
#   など外部から渡した値が無視され、常に同じ API(例: aidqapi)だけが作られる
#   不具合になります。

set -euo pipefail

FUNCTION_NAME="${FUNCTION_NAME:-qe-rag-local}"
ENDPOINT="${AWS_ENDPOINT_URL:-${LOCALSTACK_ENDPOINT:-http://localhost:4566}}"
API_ID="${API_ID:-qeragapi}"        # 固定ID (custom_id)
STAGE="${STAGE:-local}"
REGION="${AWS_REGION:-ap-northeast-1}"
ACCOUNT="000000000000"

if [ -n "${AWS_ENDPOINT_URL:-}" ]; then
  AWS="aws --endpoint-url=${AWS_ENDPOINT_URL}"
elif command -v awslocal >/dev/null 2>&1; then
  AWS="awslocal"
else
  AWS="aws --endpoint-url=${ENDPOINT}"
fi

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:function:${FUNCTION_NAME}"

echo "[1/5] Removing existing REST API '${API_ID}' if present..."
EXIST=$(${AWS} apigateway get-rest-apis --query "items[?id=='${API_ID}'].id" --output text 2>/dev/null || true)
if [ -n "${EXIST}" ] && [ "${EXIST}" != "None" ]; then
  ${AWS} apigateway delete-rest-api --rest-api-id "${API_ID}" || true
fi

echo "[2/5] Creating REST API '${API_ID}' with custom id..."
${AWS} apigateway create-rest-api --name "${API_ID}" --tags "_custom_id_=${API_ID}" >/dev/null
ROOT_ID=$(${AWS} apigateway get-resources --rest-api-id "${API_ID}" --query 'items[0].id' --output text)

echo "[3/5] Creating {proxy+} resource and ANY methods..."
PROXY_ID=$(${AWS} apigateway create-resource --rest-api-id "${API_ID}" \
  --parent-id "${ROOT_ID}" --path-part '{proxy+}' --query 'id' --output text)

# ルート (/) と {proxy+} の両方に ANY + Lambda proxy 統合を設定する
for RES in "${ROOT_ID}" "${PROXY_ID}"; do
  ${AWS} apigateway put-method --rest-api-id "${API_ID}" --resource-id "${RES}" \
    --http-method ANY --authorization-type NONE >/dev/null
  ${AWS} apigateway put-integration --rest-api-id "${API_ID}" --resource-id "${RES}" \
    --http-method ANY --type AWS_PROXY --integration-http-method POST \
    --uri "arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/${LAMBDA_ARN}/invocations" >/dev/null
done

echo "[4/5] Deploying to stage '${STAGE}'..."
${AWS} apigateway create-deployment --rest-api-id "${API_ID}" --stage-name "${STAGE}" >/dev/null

echo "[5/5] Granting API Gateway permission to invoke Lambda..."
${AWS} lambda add-permission --function-name "${FUNCTION_NAME}" \
  --statement-id apigw-invoke --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com 2>/dev/null || true

URL="${ENDPOINT}/restapis/${API_ID}/${STAGE}/_user_request_"
echo
echo "Done. RAG API endpoint (HTTP):"
echo "  ${URL}"
echo
echo "Test:"
echo "  curl -s -XPOST '${URL}/' -H 'Content-Type: application/json' \\"
echo "    -d '{\"inputs\":{\"question\":\"フレックスタイム制とは？\",\"n_queries\":1}}'"
echo
echo "genai-web からはホスト経由 (localhost:4566) の URL を使う:"
echo "  http://localhost:4566/restapis/${API_ID}/${STAGE}/_user_request_"
