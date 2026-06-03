#!/usr/bin/env bash
#
# build-apps-json.sh
# ==================
# localllm/<app>/exapp.json を集約して localllm/apps.generated.json を生成する。
#
# 目的:
#   exapps-proxy(genai-local 側) は単一の apps.json を読む実装のため無改修のまま、
#   アプリ定義を「各アプリのディレクトリ」に分散管理できるようにする。
#   アプリ追加は localllm/<新app>/exapp.json を足して本スクリプトを再実行するだけ。
#
# 生成物 localllm/apps.generated.json は genai-local の docker-compose.yaml から
#   exapps-proxy の /app/apps.json にマウントされる。
#
# 使い方:
#   bash build-apps-json.sh
#   (redeploy-all.sh の先頭からも自動で呼ばれる)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# common/localstack の2つ上が localllm/
LOCALLLM_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUT="${LOCALLLM_DIR}/apps.generated.json"

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq が必要です(brew install jq / apt-get install jq)。" >&2
  exit 1
fi

shopt -s nullglob
files=("${LOCALLLM_DIR}"/*/exapp.json)
if [ ${#files[@]} -eq 0 ]; then
  echo "ERROR: ${LOCALLLM_DIR}/*/exapp.json が1件も見つかりません。" >&2
  exit 1
fi

# 各 exapp.json ({exAppId: {...}}) を1つのオブジェクトにマージする。
# 同じ exAppId が複数あった場合は後勝ち(* の右側優先)。
jq -s 'reduce .[] as $a ({}; . * $a)' "${files[@]}" > "${OUT}"

echo "generated: ${OUT} (${#files[@]} app(s))"
for f in "${files[@]}"; do
  echo "  - ${f}"
done
