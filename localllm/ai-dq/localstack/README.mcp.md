# MCP サーバを LocalStack + Lambda + API Gateway で動かす（ローカル開発用）

このドキュメントは、`localllm/ai-dq/localstack` 配下に追加した **MCP (Model Context
Protocol) サーバ**を、AWS 実環境ではなく **LocalStack 上の Lambda + API Gateway** として
動かすための手順をまとめたものです。既存の RAG アプリ（`qe-rag-local` / `aidq-local`）と
同じデプロイ規約（環境変数化・custom id・`python3.12` / `app.handler`）に揃えています。

## アーキテクチャ

```
MCP クライアント ──HTTP(JSON-RPC 2.0)──> API Gateway ──> Lambda ──> MCP ハンドラ
                                       (すべて LocalStack 内)
```

- MCP は JSON-RPC 2.0 のメッセージ交換です。
- LocalStack の API Gateway (REST) はリクエスト/レスポンス型なので、SSE による
  ストリーミングは使わず **単発 POST で JSON-RPC を処理するステートレス実装**にしています。
- Lambda ソースは `mcp-lambda/`（ハンドラ `app.handler`）。Python 標準ライブラリのみで実装。

## 構成ファイル

| ファイル | 役割 |
|---|---|
| `mcp-lambda/app.py` | JSON-RPC 2.0 ハンドラ本体（`initialize` / `tools/list` / `tools/call` ほか） |
| `mcp-lambda/requirements.txt` | 追加依存なし（標準ライブラリのみ） |
| `mcp-lambda/test_app.py` | ディスパッチ / ツール / エラーの単体テスト |
| `deploy-mcp.sh` | MCP Lambda を LocalStack にデプロイ（`deploy.sh` 規約準拠） |
| `deploy-apigw.sh` | Lambda を REST API (proxy 統合) として HTTP 公開（既存共通スクリプト） |
| `event.mcp.sample.json` | `invoke.sh` 用の `tools/call`(add) サンプル event |

## 提供ツール

| ツール | 説明 |
|---|---|
| `echo` | 入力文字列 `text` をそのまま返す |
| `add` | 数値 `a` と `b` を加算して返す |
| `list_models` | `LMSTUDIO_BASE_URL` の `/v1/models` を叩いて利用可能モデル ID 一覧を返す（接続失敗時は空一覧にフォールバック） |

## 前提条件

- Docker / Docker Compose
- `awslocal`（`pip install awscli-local`）。無い場合は `aws --endpoint-url=http://localhost:4566` でも可
- Python 3 / pip / zip

## 手順

```bash
cd localllm/ai-dq/localstack

# 1. LocalStack 起動
docker compose up -d

# 2. MCP Lambda をデプロイ
bash deploy-mcp.sh

# 3. REST API (proxy 統合) として HTTP 公開
API_ID=mcpapi FUNCTION_NAME=mcp-local bash deploy-apigw.sh
```

公開される URL:

```
http://localhost:4566/restapis/mcpapi/local/_user_request_/
```

または、全アプリ（RAG + MCP）をまとめて再デプロイ:

```bash
bash redeploy-all.sh
```

## 動作確認（curl）

```bash
URL="http://localhost:4566/restapis/mcpapi/local/_user_request_/"

# initialize
curl -s -X POST "$URL" -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":1,"method":"initialize",
  "params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}
}'

# tools/list
curl -s -X POST "$URL" -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":2,"method":"tools/list"
}'

# tools/call (echo)
curl -s -X POST "$URL" -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":3,"method":"tools/call",
  "params":{"name":"echo","arguments":{"text":"hello"}}
}'

# tools/call (add)
curl -s -X POST "$URL" -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":4,"method":"tools/call",
  "params":{"name":"add","arguments":{"a":3,"b":4}}
}'
```

Lambda を直接 invoke して確認する場合（API Gateway を介さない）:

```bash
FUNCTION_NAME=mcp-local ./invoke.sh event.mcp.sample.json
```

## テスト

```bash
cd mcp-lambda
python -m pytest test_app.py
# pytest が無い場合は簡易ランナーでも実行できる:
python test_app.py
```

## 環境変数

`deploy-mcp.sh` から Lambda に渡されます。実行前にシェルで export して上書きできます。

| 変数 | 既定値 | 説明 |
|---|---|---|
| `FUNCTION_NAME` | `mcp-local` | Lambda 関数名 |
| `LAMBDA_TIMEOUT` | `30` | Lambda タイムアウト秒 |
| `LAMBDA_MEMORY` | `256` | Lambda メモリ(MB) |
| `LMSTUDIO_BASE_URL` | `http://host.docker.internal:1234/v1` | `list_models` が叩く OpenAI 互換エンドポイント |
| `LMSTUDIO_API_KEY` | `lm-studio` | OpenAI 互換のダミーキー |
| `MCP_SERVER_NAME` | `localstack-mcp` | `initialize` の `serverInfo.name` |
| `MCP_SERVER_VERSION` | `0.1.0` | `initialize` の `serverInfo.version` |

## 既知の制約・注意

- **ステートレス実装**です。`Mcp-Session-Id` ヘッダによるセッション管理はしていません。
  状態を保持したい場合は DynamoDB（LocalStack 対応）等に退避する設計が必要です。
- **SSE ストリーミング**はサーバ起点の通知に必要ですが、LocalStack の API Gateway では
  扱いにくいため、ローカル検証は単発 JSON-RPC に割り切っています。
- ランタイムは LocalStack が確実に対応する `python3.12` を使用します。
- 本構成は既存の RAG アプリ（`qe-rag-local` / `aidq-local`）のデプロイ・動作に影響しません。
