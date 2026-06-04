# catalog-agent

CSV をアップロードすると、**品質チェック**・**データカタログ生成**・**Text-to-SQL 品質比較**を
実行する MCP 対応エージェントです。

他の `localllm/<app>`（RAG / MCP Lambda）と異なり、本アプリは **Lambda ではなく
常駐コンテナ**（`catalog-agent`, port `8002`, ネットワーク `genai-net`）として動作します。
genai-web の AIアプリ画面からは `exapp.json`（`mode: "mcp_agent"`）経由で
`http://catalog-agent:8002/mcp` を MCP サーバとして参照します。

---

## 機能

| 機能 | 内容 |
|---|---|
| 品質チェック | カラム名・型・欠損・ユニーク制約・エンコーディングなどのルールチェック（`rules/rules_csv.yaml`） |
| データカタログ生成 | DataHub(JSON-LD) / OpenMetadata(YAML) / セマンティックビュー / マテリアライズドビュー / `catalog.md` |
| Text-to-SQL 比較 | 質問に対し、カタログ適用前/後の SQL 生成品質を LLM で比較（DB へは自動適用しない） |

> データカタログ生成と Text-to-SQL は LLM（litellm 経由の LM Studio）が必要です。
> LLM が利用できない場合でも、品質チェックは実行されます。

---

## ディレクトリ構成

```
localllm/catalog-agent/
├── Dockerfile               # python:3.11-slim, uvicorn main:app --port 8002
├── requirements.txt
├── exapp.json               # genai-web 登録用（mode: mcp_agent → /mcp）
├── main.py                  # FastAPI: REST(/analyze, /outputs, /health) + MCP(/mcp)
├── frontend/
│   └── index.html           # 単体動作用のアップロード UI
├── rules/
│   └── rules_csv.yaml       # 品質チェックルール
├── agent/
│   ├── orchestrator.py      # parse → check → catalog → textsql のまとめ役
│   ├── config.py            # 環境変数（LITELLM_BASE_URL ほか）
│   ├── models.py            # dataclass 群（ParsedData, CheckResult, ...）
│   ├── parser/              # CSV パース（chardet でエンコーディング判定）
│   ├── checker/             # ルールチェック
│   ├── catalog/             # カタログ各種エクスポータ／ビュー生成
│   ├── textsql/             # SQLite ロード・SQL 生成・評価・比較
│   ├── llm/                 # litellm クライアント
│   └── prompts/             # LLM プロンプトテンプレート
└── tests/                   # pytest（REST / MCP / 各コンポーネント）
```

---

## エンドポイント

### REST

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/health` | ヘルスチェック（`{"status":"ok"}`） |
| `POST` | `/analyze` | `multipart/form-data` で CSV(`file`) と任意の `questions`(JSON配列文字列)を受け取り分析 |
| `GET` | `/outputs/{table_name}/{filename}` | 生成済みカタログ成果物のダウンロード |
| `GET` | `/` | フロントエンド（`frontend/index.html`） |

### MCP（`POST /mcp`, JSON-RPC 2.0）

単発 POST で JSON-RPC を処理するステートレス実装です（SSE ストリーミングは未使用）。

| method | 説明 |
|---|---|
| `initialize` | プロトコルバージョン・サーバ情報を返す |
| `notifications/initialized` | 通知（`202` を返す） |
| `tools/list` | 提供ツール一覧（`analyze_csv`） |
| `tools/call` | `analyze_csv` を実行 |

`analyze_csv` の引数:

| 引数 | 必須 | 説明 |
|---|---|---|
| `filename` | ✓ | 元のファイル名（`.csv` で終わる必要あり） |
| `content_base64` | ✓ | CSV 本体を base64 エンコードした文字列 |
| `questions` | | Text-to-SQL 用の質問リスト（文字列配列） |

実行結果は `result.content[0].text` に分析結果 JSON（`check_results` / `catalog_outputs` /
`textsql_comparison` を含む）を文字列で返します。

---

## ローカル実行

```bash
cd localllm/catalog-agent

# Docker
docker build -t catalog-agent .
docker run --rm -p 8002:8002 \
  -e LITELLM_BASE_URL=http://host.docker.internal:4000 \
  -e LLM_MODEL=chat \
  catalog-agent

# もしくはローカル直接
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8002
```

ブラウザで `http://localhost:8002/` を開くと CSV アップロード UI が使えます。

### 環境変数（`agent/config.py`）

| 変数 | 既定値 | 説明 |
|---|---|---|
| `LITELLM_BASE_URL` | `http://litellm:4000` | litellm のベース URL |
| `LITELLM_API_KEY` | `sk-localdummy` | API キー |
| `LLM_MODEL` | `chat` | 使用モデル名 |
| `OUTPUT_DIR` | `output/` | カタログ成果物の出力先 |
| `LOG_LEVEL` | `INFO` | ログレベル |
| `MAX_COLUMNS` | `50` | 取り込むカラム数の上限 |

MCP 関連（`main.py`）:

| 変数 | 既定値 | 説明 |
|---|---|---|
| `MCP_SERVER_NAME` | `catalog-agent-mcp` | MCP サーバ名 |
| `MCP_SERVER_VERSION` | `0.1.0` | MCP サーババージョン |

---

## 動作確認（MCP）

```bash
# tools/list
curl -s -XPOST http://localhost:8002/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# analyze_csv（CSV を base64 で渡す）
B64=$(printf 'id,name\n1,Alice\n' | base64)
curl -s -XPOST http://localhost:8002/mcp \
  -H 'Content-Type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"analyze_csv\",\"arguments\":{\"filename\":\"test.csv\",\"content_base64\":\"$B64\"}}}"
```

---

## genai-web への登録

`exapp.json`（`mode: "mcp_agent"`）が `mcpServers.catalog.url` に
`http://catalog-agent:8002/mcp` を指定しています。`build-apps-json.sh` による
`apps.generated.json` / `govais.generated.env` 生成フローに取り込まれます。

> 他アプリと違い API Gateway / Lambda は経由しません。`catalog-agent` コンテナが
> `genai-net` 上に起動している必要があります。

---

## テスト

```bash
cd localllm/catalog-agent
pip install -r requirements.txt
pytest
```

| テスト | 対象 |
|---|---|
| `test_health.py` | `/health` |
| `test_parser.py` | CSV パース（UTF-8 / Shift_JIS / 空 / カラム上限） |
| `test_checker.py` | 品質チェックルール（STR/TYP/INT 各種） |
| `test_analyze_check.py` | `/analyze`（成功 / 空 / 非CSV / LLM不通 / 所要時間） |
| `test_catalog.py` | カタログ各エクスポータ・ビュー生成 |
| `test_textsql.py` | SQLite ロード・SQL生成・評価・比較 |
| `test_integration.py` | `/analyze` フルパイプライン（LLM モック） |
| `test_outputs_download.py` | `/outputs` ダウンロード |
| `test_llm.py` | litellm クライアント（リトライ） |
| `test_mcp.py` | `/mcp`（initialize / tools/list / tools/call ほか） |
