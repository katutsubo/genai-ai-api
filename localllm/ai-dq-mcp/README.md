# MCP サーバを LocalStack + Lambda + API Gateway で動かす（ローカル開発用）

このドキュメントは、`localllm/ai-dq-mcp/localstack` 配下の **MCP (Model Context
Protocol) サーバ**を、AWS 実環境ではなく **LocalStack 上の Lambda + API Gateway** として
動かすための手順をまとめたものです。既存の RAG アプリ（`qe-rag-local` / `aidq-local`）と
同じデプロイ規約（環境変数化・custom id・`python3.12` / `app.handler`）に揃えています。

> **このディレクトリについて**
> もともと MCP は `ai-dq/localstack` に同居していましたが、`genai-local/exapps-proxy/apps.json`
> の3アプリ ↔ ディレクトリ対応を明確にするため、MCP 専用ディレクトリ `ai-dq-mcp` に分離しました。
>
> | exAppId | ディレクトリ | API_ID / FUNCTION_NAME |
> |---|---|---|
> | `488aa4a6-…` | `localllm/query-expansion-rag` | `qeragapi` / `qe-rag-local` |
> | `E39FFF9B-…` | `localllm/ai-dq` | `aidqapi` / `aidq-local` |
> | `F1A2B3C4-…` | `localllm/ai-dq-mcp`（本ディレクトリ） | `mcpapi` / `mcp-local` |
>
> **共有スクリプト**（`deploy-apigw.sh` / `invoke.sh` / `redeploy-all.sh`）は
> `localllm/common/localstack/` に集約しています。

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

ディレクトリ構成:

```
localllm/
├── ai-dq-mcp/
│   └── localstack/
│       ├── mcp-lambda/
│       │   ├── app.py            … JSON-RPC 2.0 ハンドラ本体
│       │   ├── requirements.txt  … 追加依存なし（標準ライブラリのみ）
│       │   └── test_app.py       … 単体テスト
│       ├── deploy-mcp.sh         … MCP Lambda を LocalStack にデプロイ
│       ├── event.mcp.sample.json … tools/call(add) サンプル event
│       ├── event.mcp.file.sample.json … tools/call(process_file) サンプル event
│       ├── invoke-mcp-file.sh    … ローカルファイルを process_file に投げる
│       └── README.md             … 本ファイル
└── common/
    └── localstack/
        ├── deploy-apigw.sh       … Lambda を REST API(proxy統合)として HTTP 公開（共有）
        ├── invoke.sh             … Lambda を直接 invoke するサンプル（共有）
        └── redeploy-all.sh       … RAG + MCP をまとめて再デプロイ（共有・統合版）
```

| ファイル | 役割 |
|---|---|
| `mcp-lambda/app.py` | JSON-RPC 2.0 ハンドラ本体（`initialize` / `tools/list` / `tools/call` ほか） |
| `mcp-lambda/requirements.txt` | 追加依存なし（標準ライブラリのみ） |
| `mcp-lambda/test_app.py` | ディスパッチ / ツール / エラーの単体テスト |
| `deploy-mcp.sh` | MCP Lambda を LocalStack にデプロイ（`deploy.sh` 規約準拠） |
| `../../common/localstack/deploy-apigw.sh` | Lambda を REST API (proxy 統合) として HTTP 公開（共有） |
| `event.mcp.sample.json` | `invoke.sh` 用の `tools/call`(add) サンプル event |
| `event.mcp.file.sample.json` | `invoke.sh` 用の `tools/call`(process_file) サンプル event |
| `invoke-mcp-file.sh` | ローカルファイルを base64 化して `process_file` に投げるサンプルスクリプト |

## 提供ツール

| ツール | 説明 |
|---|---|
| `echo` | 入力文字列 `text` をそのまま返す |
| `add` | 数値 `a` と `b` を加算して返す |
| `list_models` | `LMSTUDIO_BASE_URL` の `/v1/models` を叩いて利用可能モデル ID 一覧を返す（接続失敗時は空一覧にフォールバック） |
| `process_file` | アップロードされたファイル（base64）を受け取り、内容を解析して要約（ファイル名・バイトサイズ・テキスト判定・行数/文字数・先頭プレビュー）を返す |

### `process_file` の入力スキーマ

| 引数 | 型 | 必須 | 説明 |
|---|---|---|---|
| `filename` | string | ○ | 元のファイル名（例: `report.txt`） |
| `content_base64` | string | ○ | ファイル本体を base64 エンコードした文字列 |
| `content_type` | string | - | MIME タイプ（任意、例: `text/plain`）。`mime_type` でも可 |

返却される要約（`content[].text` に JSON 文字列で格納）:

| キー | 説明 |
|---|---|
| `filename` | 受け取ったファイル名 |
| `content_type` | 渡された MIME タイプ（任意） |
| `size_bytes` | base64 デコード後のバイト数 |
| `is_text` | UTF-8 テキストとしてデコードできたか |
| `char_count` | （テキスト時）文字数 |
| `line_count` | （テキスト時）行数 |
| `preview` | （テキスト時）先頭 `MCP_FILE_PREVIEW_CHARS` 文字（既定 2000） |
| `preview_truncated` | プレビューが切り詰められたか |

- base64 が不正、または `filename` / `content_base64` が欠けている場合は Lambda を落とさず
  JSON-RPC error `-32602` を返します。
- UTF-8 として解釈できないバイナリは `is_text: false` となり、`preview` は省略されます。

## 前提条件

- Docker / Docker Compose
- `awslocal`（`pip install awscli-local`）。無い場合は `aws --endpoint-url=http://localhost:4566` でも可
- Python 3 / pip / zip

## 手順

```bash
cd localllm/ai-dq-mcp/localstack

# 1. LocalStack 起動（genai-local 側で起動済みならスキップ可）
#    ai-dq/localstack/docker-compose.yml を使う場合:
#    (cd ../../ai-dq/localstack && docker compose up -d)

# 2. MCP Lambda をデプロイ
bash deploy-mcp.sh

# 3. REST API (proxy 統合) として HTTP 公開（共有スクリプトを common から呼ぶ）
API_ID=mcpapi FUNCTION_NAME=mcp-local bash ../../common/localstack/deploy-apigw.sh
```

公開される URL:

```
http://localhost:4566/restapis/mcpapi/local/_user_request_/
```

または、全アプリ（RAG + MCP）をまとめて再デプロイ（共有の統合スクリプト）:

```bash
cd localllm/common/localstack
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

### ファイルアップロード（`process_file`）

ファイルを base64 化して `tools/call` で送ります。短いテキストなら curl でも書けます:

```bash
URL="http://localhost:4566/restapis/mcpapi/local/_user_request_/"
B64="$(printf '日本語のテキスト\n2 行目\n' | base64 | tr -d '\n')"

curl -s -X POST "$URL" -H 'Content-Type: application/json' -d "{
  \"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"tools/call\",
  \"params\":{\"name\":\"process_file\",\"arguments\":{
    \"filename\":\"sample.txt\",\"content_type\":\"text/plain\",\"content_base64\":\"${B64}\"
  }}
}"
```

実ファイルを投げる場合は付属スクリプトが便利です（base64 化・JSON 組み立て・結果整形を自動化）:

```bash
cd localllm/ai-dq-mcp/localstack

# API Gateway 経由で実ファイルを process_file に投げる
# （サンプル KB ファイルは ai-dq 側に残っているため相対パスで指定）
bash invoke-mcp-file.sh ../../ai-dq/localstack/local_kb_docs.json

# エンドポイントや API ID を変える場合（genai-net 内コンテナ等）
AWS_ENDPOINT_URL=http://localstack:4566 API_ID=mcpapi \
  bash invoke-mcp-file.sh ./some.txt
```

Lambda を直接 invoke して確認する場合（API Gateway を介さない・共有 invoke.sh を使用）:

```bash
cd localllm/ai-dq-mcp/localstack

# add サンプル
FUNCTION_NAME=mcp-local bash ../../common/localstack/invoke.sh ./event.mcp.sample.json

# process_file サンプル
FUNCTION_NAME=mcp-local bash ../../common/localstack/invoke.sh ./event.mcp.file.sample.json
```

## テスト

```bash
cd localllm/ai-dq-mcp/localstack/mcp-lambda
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
| `MCP_FILE_PREVIEW_CHARS` | `2000` | `process_file` が返すテキストプレビューの最大文字数 |

## 既知の制約・注意

- **ステートレス実装**です。`Mcp-Session-Id` ヘッダによるセッション管理はしていません。
  状態を保持したい場合は DynamoDB（LocalStack 対応）等に退避する設計が必要です。
- **SSE ストリーミング**はサーバ起点の通知に必要ですが、LocalStack の API Gateway では
  扱いにくいため、ローカル検証は単発 JSON-RPC に割り切っています。
- `process_file` は単発リクエスト内でファイル本体（base64）を受け取ります。API Gateway /
  Lambda のペイロード上限があるため、巨大ファイルは S3 経由にするなどの設計が必要です。
- ランタイムは LocalStack が確実に対応する `python3.12` を使用します。
- 本構成は既存の RAG アプリ（`qe-rag-local` / `aidq-local`）のデプロイ・動作に影響しません。
- **API_ID / FUNCTION_NAME は不変**（`mcpapi` / `mcp-local`）のため、`genai-local/exapps-proxy/apps.json`
  の `mcpServers[].url` の変更は不要です。