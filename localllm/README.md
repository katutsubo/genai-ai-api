# 新規 AI アプリ追加手順（ローカル版）

genai-web を**無改修**のまま、AIアプリ画面 `/apps/{teamId}/{exAppId}` から
新しい RAG / LLM アプリを呼び出せるようにする手順をまとめます。

## 全体像

新規アプリ追加は 3 レイヤーの作業です。

| レイヤー | 作業内容 | 触る場所 |
|---|---|---|
| ① ロジック | アプリ固有の挙動(プロンプト・モデル・推論パラメータ) | `genai-ai-api/localllm/ai-dq/config/apps/<app>.toml` |
| ② デプロイ／公開 | Lambda を別名で立て、別 custom id で HTTP 公開 | `deploy.sh` / `deploy-apigw.sh`（環境変数で制御） |
| ③ 画面 | genai-web の AIアプリ画面に出す（フォーム定義＋呼び先URL） | `exapps-proxy/apps.json` |

### 識別子の対応関係

1 つのアプリは以下の名前で紐づきます。**衝突しない値**を決めてください。

| 項目 | 役割 | 例(クエリ拡張RAG) | 例(AI-DQ) |
|---|---|---|---|
| `<app>` | アプリ短縮名 | `qerag` | `aidq` |
| TOML | アプリ個別設定 | `qerag.toml` | `aidq.toml` |
| `FUNCTION_NAME` | Lambda 関数名 | `qe-rag-local` | `aidq-local` |
| `API_ID` | API Gateway custom id | `qeragapi` | `aidqapi` |
| `ragApiUrl` | 公開HTTP URL | `.../restapis/qeragapi/...` | `.../restapis/aidqapi/...` |
| `exAppId` | 画面URLのアプリID(任意UUID) | `488aa4a6-...` | `E39FFF9B-...` |

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

### 1. アプリ設定 TOML を作成（① ロジック）

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

### 2. Lambda をデプロイ（② デプロイ）

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

### 3. API Gateway で HTTP 公開（② 公開）

別 custom id `API_ID` で公開します。

```bash
API_ID=<app>api \
FUNCTION_NAME=<app>-local \
bash deploy-apigw.sh
```

公開URL:
```
http://localhost:4566/restapis/<app>api/local/_user_request_/
```

### 4. 動作確認（Lambda 単体）

```bash
# 設定が入ったか(APP_PARAM_FILE が見えればOK)
aws --endpoint-url=http://localhost:4566 lambda get-function-configuration \
  --function-name <app>-local --query 'Environment.Variables'

# 実行(responseFooter が TOML の文言になれば設定が効いている)
curl -s -XPOST 'http://localhost:4566/restapis/<app>api/local/_user_request_/' \
  -H 'Content-Type: application/json' \
  -d '{"inputs":{"question":"テスト質問","n_queries":2}}'
# → {"statusCode":200,"body":"{\"outputs\": ...}"} を期待
```

### 5. 画面に登録（③ 画面）

`exapps-proxy/apps.json` に新しい `exAppId` のエントリを追加します。

```bash
# exAppId 用 UUID を生成
uuidgen
```

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

「質問」を入力して「実行」 → 新アプリの挙動で回答が表示されます。

### 7. （任意）ホーム画面の「おすすめアプリ」に出す

`docker-compose.yaml` の `genai-web` 環境変数に exAppId を追加。

```yaml
VITE_APP_GOVAIS_FOR_HOMEPAGE: '["488aa4a6-9e86-4ab5-a68b-12efb5e80cec","<追加したexAppId>"]'
```
反映: `docker compose up -d genai-web`

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

- [ ] `config/apps/<app>.toml` を作成（① ロジック）
- [ ] `FUNCTION_NAME=<app>-local APP_PARAM_FILE=<app>.toml` で `deploy.sh`（② デプロイ）
- [ ] `API_ID=<app>api` で `deploy-apigw.sh`（② 公開）
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