# 新規 AI アプリ追加手順（ローカル版）

genai-web を**無改修**のまま、AIアプリ画面 `/apps/{teamId}/{exAppId}` から
新しい RAG / LLM / MCP アプリを呼び出せるようにする手順をまとめます。

## 全体像

新規アプリ追加は 3 レイヤーの作業です。

| レイヤー | 作業内容 | 触る場所 |
|---|---|---|
| ① ロジック | アプリ固有の挙動(プロンプト・モデル・推論パラメータ / MCPツール) | `genai-ai-api/localllm/<app>/...` |
| ② デプロイ／公開 | Lambda を別名で立て、別 custom id で HTTP 公開 | 各 `<app>/localstack/deploy*.sh` + 共有 `common/localstack/deploy-apigw.sh` |
| ③ 画面 | genai-web の AIアプリ画面に出す（フォーム定義＋呼び先URL） | `exapps-proxy/apps.json` |

### アプリ ↔ ディレクトリ対応

`exapps-proxy/apps.json` に登録された各アプリ(exAppId)は、`localllm` 配下の
ディレクトリと 1 対 1 で対応します。

| exAppId | ディレクトリ | 種別 | API_ID / FUNCTION_NAME |
|---|---|---|---|
| `488aa4a6-9e86-4ab5-a68b-12efb5e80cec` | `localllm/query-expansion-rag` | RAG(クエリ拡張) | `qeragapi` / `qe-rag-local` |
| `E39FFF9B-49F6-4A32-A200-AE67C6321FD5` | `localllm/ai-dq` | RAG(拡張なし) | `aidqapi` / `aidq-local` |
| `F1A2B3C4-D5E6-47F8-9A0B-1C2D3E4F5A6B` | `localllm/ai-dq-mcp` | MCP エージェント | `mcpapi` / `mcp-local` |

共有スクリプト（複数アプリで使い回すもの）は `localllm/common/localstack/` に集約しています。

```
localllm/
├── query-expansion-rag/      # ① RAG(クエリ拡張)
├── ai-dq/                    # ② RAG(拡張なし)
│   └── localstack/
│       ├── deploy.sh         #   RAG 用デプロイ
│       └── (RAG 専用ファイル)
├── ai-dq-mcp/               # ③ MCP エージェント
│   └── localstack/
│       ├── mcp-lambda/       #   MCP Lambda ソース
│       ├── deploy-mcp.sh     #   MCP 用デプロイ
│       ├── invoke-mcp-file.sh
│       ├── event.mcp*.json
│       └── README.md         #   MCP 詳細手順
└── common/                  # 共有スクリプト
    └── localstack/
        ├── deploy-apigw.sh   #   Lambda を HTTP 公開（全アプリ共通）
        ├── invoke.sh         #   Lambda 直接 invoke（全アプリ共通）
        └── redeploy-all.sh   #   RAG + MCP をまとめて再デプロイ
```

### 識別子の対応関係

1 つのアプリは以下の名前で紐づきます。**衝突しない値**を決めてください。

| 項目 | 役割 | 例(クエリ拡張RAG) | 例(AI-DQ) | 例(MCP) |
|---|---|---|---|---|
| `<app>` | アプリ短縮名 | `qerag` | `aidq` | `mcp` |
| ディレクトリ | ロジック配置先 | `query-expansion-rag` | `ai-dq` | `ai-dq-mcp` |
| 設定 | アプリ個別設定 | `qerag.toml` | `aidq.toml` | （TOML不要・環境変数） |
| `FUNCTION_NAME` | Lambda 関数名 | `qe-rag-local` | `aidq-local` | `mcp-local` |
| `API_ID` | API Gateway custom id | `qeragapi` | `aidqapi` | `mcpapi` |
| 公開URL | HTTP エンドポイント | `.../restapis/qeragapi/...` | `.../restapis/aidqapi/...` | `.../restapis/mcpapi/...` |
| `exAppId` | 画面URLのアプリID(任意UUID) | `488aa4a6-...` | `E39FFF9B-...` | `F1A2B3C4-...` |

> **重要:** `API_ID` / `FUNCTION_NAME` は公開 URL（`.../restapis/<API_ID>/local/...`）に直結し、
> `exapps-proxy/apps.json` の `ragApiUrl` / `mcpServers[].url` が参照しています。
> ディレクトリを移動・整理しても、これらの規約値は変更しないでください
> （変えると apps.json 側の修正が必要になります）。

---

## 手順

### 0. 前提

- `genai-local` の基盤が起動済み
  ```bash
  docker compose up -d localstack postgres litellm exapps-proxy
  ```
- LM Studio に軽量モデル(3B〜7B)をロード済み
- サブモジュール `genai-ai-api` が最新化済み
  ```bash
  cd genai-ai-api && git pull origin localstack-lmstudio && cd -
  ```

### 1. アプリ設定 TOML を作成（① ロジック / RAG の場合）

`genai-ai-api/localllm/ai-dq/config/apps/<app>.toml` を作成します。
`config/defaults/*.toml` を**上書きしたい項目だけ**書きます（未記述は既定値）。

```toml
# config/apps/<app>.toml
name = "<app>"
description = "<アプリの説明>"

# 回答末尾フッター(APP_NAME 指定時に読まれる)
responseFooter = "※ この回答は <アプリ名> により生成されています。"

# 回答生成の挙動を上書き
[answer_generation]
systemPrompt = '''
あなたは <アプリ名> 専用のアシスタントです。
提供されたコンテキストのみを根拠に、簡潔かつ正確に日本語で回答してください。
'''
temperature = 0
maxTokens = 1024

# クエリ拡張の挙動を上書き(任意)
[query_expansion]
temperature = 0
```

> 利用可能なキーは `config/defaults/*.toml` に準拠します。
> `modelId` / `systemPrompt` / `temperature` / `maxTokens` / `topP` / `topK` /
> `stopSequences` / `maxCitations` などが `config_manager.py` で参照されます。
>
> **MCP アプリ（ai-dq-mcp）には TOML はありません。** ツールは `mcp-lambda/app.py` に実装し、
> 接続先などは環境変数で渡します。詳細は `localllm/ai-dq-mcp/localstack/README.md` を参照。

### 2. Lambda をデプロイ（② デプロイ）

#### RAG アプリの場合（ai-dq）

別名 `FUNCTION_NAME` ＋ アプリ設定 `APP_PARAM_FILE` / `APP_NAME` を渡して実行します。

```bash
cd genai-ai-api/localllm/ai-dq/localstack

AWS_ENDPOINT_URL=http://localhost:4566 \
FUNCTION_NAME=<app>-local \
APP_NAME=<app> \
APP_PARAM_FILE=<app>.toml \
LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1 \
LMSTUDIO_API_KEY=lm-studio \
LMSTUDIO_CHAT_MODEL="" \
LMSTUDIO_EMBEDDING_MODEL="" \
bash deploy.sh
```

> `LMSTUDIO_CHAT_MODEL=""` は LM Studio の `/v1/models` から動的取得。
> LiteLLM 経由にする場合は
> `LMSTUDIO_BASE_URL=http://litellm:4000/v1 LMSTUDIO_API_KEY=sk-localdummy LMSTUDIO_CHAT_MODEL=chat LMSTUDIO_EMBEDDING_MODEL=embed` に変更。

#### MCP アプリの場合（ai-dq-mcp）

```bash
cd genai-ai-api/localllm/ai-dq-mcp/localstack
FUNCTION_NAME=mcp-local bash deploy-mcp.sh
```

### 3. API Gateway で HTTP 公開（② 公開）

別 custom id `API_ID` で公開します。**共有スクリプトを `common/localstack/` から呼びます。**

```bash
# RAG（ai-dq/localstack から）
API_ID=<app>api FUNCTION_NAME=<app>-local \
  bash ../../common/localstack/deploy-apigw.sh

# MCP（ai-dq-mcp/localstack から）
API_ID=mcpapi FUNCTION_NAME=mcp-local \
  bash ../../common/localstack/deploy-apigw.sh
```

公開URL:
```
http://localhost:4566/restapis/<app>api/local/_user_request_/
```

> すべてのアプリ（RAG + MCP）をまとめて復旧したい場合は共有の統合スクリプトが便利です:
> ```bash
> cd genai-ai-api/localllm/common/localstack
> bash redeploy-all.sh
> ```

### 4. 動作確認（Lambda 単体）

```bash
# 設定が入ったか(APP_PARAM_FILE が見えればOK)
aws --endpoint-url=http://localhost:4566 lambda get-function-configuration \
  --function-name <app>-local --query 'Environment.Variables'

# 実行(RAG: responseFooter が TOML の文言になれば設定が効いている)
curl -s -XPOST 'http://localhost:4566/restapis/<app>api/local/_user_request_/' \
  -H 'Content-Type: application/json' \
  -d '{"inputs":{"question":"テスト質問","n_queries":2}}'
# → {"statusCode":200,"body":"{\"outputs\": ...}"} を期待

# 実行(MCP: tools/list)
curl -s -XPOST 'http://localhost:4566/restapis/mcpapi/local/_user_request_/' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### 5. 画面に登録（③ 画面）

`exapps-proxy/apps.json` に新しい `exAppId` のエントリを追加します。

```bash
# exAppId 用 UUID を生成
uuidgen
```

RAG アプリの例:

```json
{
  "<生成したUUID>": {
    "exAppName": "<アプリ名>",
    "description": "<アプリの説明>",
    "ragApiUrl": "http://localstack:4566/restapis/<app>api/local/_user_request_/",
    "placeholder": {
      "question": { "type": "textarea", "title": "質問", "required": true, "max_length": 1000 },
      "n_queries": { "type": "number", "title": "クエリ拡張数", "default_value": "1", "min": 1, "max": 5 },
      "output_in_detail": { "type": "hidden", "default_value": "false" }
    }
  }
}
```

MCP アプリの例（`mode: "mcp_agent"`）:

```json
{
  "<生成したUUID>": {
    "exAppName": "MCPエージェント（ローカル）",
    "description": "プロンプトからMCPサーバとツールを指定して実行します。",
    "mode": "mcp_agent",
    "mcpServers": {
      "local": {
        "name": "ローカルMCP",
        "url": "http://localstack:4566/restapis/mcpapi/local/_user_request_/",
        "description": "echo / add / list_models / process_file"
      }
    },
    "placeholder": {
      "prompt": { "type": "textarea", "title": "プロンプト", "required": true }
    }
  }
}
```

反映:
```bash
cd genai-local
docker compose restart exapps-proxy
curl -s http://localhost:4100/healthz | jq '.apps'
# → 追加した exAppId が一覧に出ればOK
```

### 6. ブラウザで確認

```
http://localhost:5173/apps/{任意teamId}/{追加したexAppId}
```

「質問」やプロンプトを入力して「実行」 → 新アプリの挙動で回答が表示されます。

### 7. （任意）ホーム画面の「おすすめアプリ」に出す

ホーム画面の AIアプリ一覧（genai-web の `VITE_APP_GOVAIS_FOR_HOMEPAGE`）は、
**`docker-compose.yaml` にハードコードせず**、各アプリの `exapp.json` から自動生成します。
`build-apps-json.sh` が `apps.generated.json` と同時に
`localllm/govais.generated.env` を生成し、genai-web が `env_file` で取り込みます。

```bash
# exapp.json を追加・編集したら再生成（apps.generated.json と govais.generated.env を更新）
cd genai-ai-api/localllm/common/localstack
bash build-apps-json.sh
# ※ redeploy-all.sh は先頭で build-apps-json.sh を自動実行する

# genai-web を作り直して反映（VITE_APP_* はビルド時に埋め込まれるため restart 不可）
cd -   # genai-local ルートへ
docker compose up -d --force-recreate genai-web
```

生成される `govais.generated.env` は次の形式です（`exapp.json` の `exAppName` →
`title`、キー → `exAppId`、`description` を自動補完）。

```env
VITE_APP_GOVAIS_FOR_HOMEPAGE=[{"title":"...","teamId":"00000000-0000-0000-0000-000000000000","exAppId":"...","description":"..."}]
```

> ⚠️ genai-web 側の `docker-compose.yaml` では、`env_file` の値が効くように
> `environment` に `VITE_APP_GOVAIS_FOR_HOMEPAGE` を**書かないでください**
> （`environment` は `env_file` より優先されるため上書きされます）。
>
> ℹ️ 一覧から外したいアプリがある場合は、その `exapp.json` を含めない運用にするか、
> 生成後の `govais.generated.env` を手で編集してください（再生成で上書きされます）。
> `teamId` を変えたい場合は `HOMEPAGE_TEAM_ID=<uuid> bash build-apps-json.sh`。

---

## 画面（フォーム）のカスタマイズ

`placeholder` を編集すると、genai-web 無改修のままフォームを変更できます。
編集後は `docker compose restart exapps-proxy` で即反映されます。

### 入力部品の種類（GovAIFormUI 形式）

| type | 用途 | 主な追加属性 |
|---|---|---|
| `text` | 1行テキスト | `min_length` / `max_length` |
| `textarea` | 複数行テキスト | `min_length` / `max_length` |
| `number` | 数値 | `min` / `max` |
| `select` | プルダウン | `items: [{title, value}]` |
| `radio` | ラジオ | `items: [{title, value}]` |
| `checkbox` | チェックボックス | `items: [{title, value}]` |
| `hidden` | 非表示固定値 | `default_value` |

共通属性: `title`（ラベル）/ `desc`（補足）/ `required` / `default_value`

### 例: 部署選択を追加する

```json
"placeholder": {
  "question": { "type": "textarea", "title": "質問", "required": true },
  "department": {
    "type": "select", "title": "対象部署",
    "items": [
      { "title": "総務", "value": "general" },
      { "title": "人事", "value": "hr" }
    ]
  },
  "n_queries": { "type": "hidden", "default_value": "1" }
}
```

> フォーム項目は `inputs` としてそのまま Lambda に渡ります。新項目を
> Lambda 側で使う場合は `app.py` の `parse_input` で受け取る実装が必要です。

---

## チェックリスト

新規アプリ `<app>` を追加するとき:

- [ ] ディレクトリを決める（RAG: `ai-dq` 流用 / MCP: `ai-dq-mcp` 流用 or 新規 `<app>`）
- [ ] （RAG）`config/apps/<app>.toml` を作成（① ロジック）
- [ ] （RAG）`FUNCTION_NAME=<app>-local APP_PARAM_FILE=<app>.toml` で `deploy.sh`（② デプロイ）
- [ ] （MCP）`FUNCTION_NAME=mcp-local` で `deploy-mcp.sh`（② デプロイ）
- [ ] `API_ID=<app>api` で `common/localstack/deploy-apigw.sh`（② 公開）
- [ ] Lambda 単体で動作確認（手順4）
- [ ] `exapps-proxy/apps.json` に exAppId エントリ追加（③ 画面）
- [ ] `docker compose restart exapps-proxy`
- [ ] ブラウザ `/apps/任意UUID/<exAppId>` で確認

---

## トラブルシュート

| 症状 | 原因 / 対処 |
|---|---|
| 設定が反映されない | `git submodule update --remote` で最新の deploy.sh/TOML を取得後、再 deploy |
| `responseFooter` が変わらない | `APP_NAME` / `APP_PARAM_FILE` が未指定。手順2の env を確認 |
| `question is required` | リクエスト形式不正。`exapps-proxy` は `{"inputs":{...}}` を直接送る |
| 別アプリなのに同じ画面 | `apps.json` に該当 exAppId が無く先頭にフォールバック。`/healthz` の `apps` を確認 |
| 実行が 400 / メモリ不足 | LM Studio のモデルが大きすぎる。3B〜7B級に変更 |
| `Task timed out` | `LAMBDA_TIMEOUT`(既定900秒)を確認。ローカルLLMは低速 |
| `deploy-apigw.sh が見つからない` | 共有スクリプトは `common/localstack/` に移動済み。`bash ../../common/localstack/deploy-apigw.sh` で呼ぶ |
| MCP が応答しない | `API_ID=mcpapi FUNCTION_NAME=mcp-local` で公開したか確認。詳細は `ai-dq-mcp/localstack/README.md` |
| ホーム画面にアプリが出ない/古い | `build-apps-json.sh` を再実行して `govais.generated.env` を更新し、`docker compose up -d --force-recreate genai-web` で作り直す。`docker-compose.yaml` の `environment` に `VITE_APP_GOVAIS_FOR_HOMEPAGE` を書くと env_file が上書きされるので書かない |
