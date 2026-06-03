## 目的

`genai-local/exapps-proxy/apps.json` に登録された3つのAIアプリと、`localllm` 配下の
ロジック実装ディレクトリを1対1で対応させ、見通しを良くする。特に `ai-dq` に同居していた
MCP 関連を独立ディレクトリ `ai-dq-mcp` に分離し、複数アプリで使う共有スクリプトを
`common/localstack` に集約する。

| exAppId | ディレクトリ | API_ID / FUNCTION_NAME |
|---|---|---|
| `488aa4a6-9e86-4ab5-a68b-12efb5e80cec` | `localllm/query-expansion-rag` | `qeragapi` / `qe-rag-local` |
| `E39FFF9B-49F6-4A32-A200-AE67C6321FD5` | `localllm/ai-dq` | `aidqapi` / `aidq-local` |
| `F1A2B3C4-D5E6-47F8-9A0B-1C2D3E4F5A6B` | `localllm/ai-dq-mcp`（新規） | `mcpapi` / `mcp-local` |

## 変更後のディレクトリ構成

```
localllm/
├── query-expansion-rag/        # ① RAG(クエリ拡張) … 変更なし
├── ai-dq/
│   └── localstack/             # ② RAG(拡張なし) … RAG 専用ファイルのみ残す
│       ├── deploy.sh
│       ├── docker-compose.yml
│       ├── genai-local.deploy.compose.yaml
│       ├── event.sample.json
│       ├── local_kb_docs.json
│       └── README.md
├── ai-dq-mcp/
│   └── localstack/             # ③ MCP … 新規・MCPを集約
│       ├── mcp-lambda/
│       │   ├── app.py
│       │   ├── requirements.txt
│       │   └── test_app.py
│       ├── deploy-mcp.sh
│       ├── invoke-mcp-file.sh
│       ├── event.mcp.sample.json
│       ├── event.mcp.file.sample.json
│       └── README.md           # 旧 ai-dq/localstack/README.mcp.md
└── common/
    └── localstack/             # 共有スクリプト
        ├── deploy-apigw.sh
        ├── invoke.sh
        └── redeploy-all.sh     # RAG + MCP を新パスで再デプロイする統合版
```

## 変更内容

### 追加（新パス）
- `ai-dq-mcp/localstack/mcp-lambda/`（`app.py` / `requirements.txt` / `test_app.py`）
- `ai-dq-mcp/localstack/deploy-mcp.sh`（`Next:` 案内を `../../common/localstack/deploy-apigw.sh` に修正）
- `ai-dq-mcp/localstack/invoke-mcp-file.sh`（公開手順の案内パスを common 配下に修正）
- `ai-dq-mcp/localstack/event.mcp.sample.json` / `event.mcp.file.sample.json`
- `ai-dq-mcp/localstack/README.md`（旧 `README.mcp.md` を新構成へ更新）
- `common/localstack/deploy-apigw.sh`（汎用・内容は従来どおり）
- `common/localstack/invoke.sh`（event ファイルを引数で受け取る汎用版に調整）
- `common/localstack/redeploy-all.sh`（`ai-dq`(RAG) と `ai-dq-mcp`(MCP) を各新パスから呼ぶ統合版）

### 削除（旧パス・移設済み）
- `ai-dq/localstack/mcp-lambda/`
- `ai-dq/localstack/deploy-mcp.sh` / `invoke-mcp-file.sh`
- `ai-dq/localstack/event.mcp.sample.json` / `event.mcp.file.sample.json`
- `ai-dq/localstack/README.mcp.md`
- `ai-dq/localstack/deploy-apigw.sh` / `invoke.sh` / `redeploy-all.sh`（common へ移設）
- `ai-dq/localstack/APP_PARAM_FILE=aidq.toml`（0バイトの誤コミットファイル）

### ドキュメント更新
- `localllm/README.md`: 「全体像」「アプリ↔ディレクトリ対応」「識別子の対応関係」に
  `ai-dq-mcp` / `common` を反映。デプロイ手順の例パスを新構成（共有スクリプトは
  `../../common/localstack/deploy-apigw.sh` から呼ぶ）に更新。MCP アプリの登録例も追記。

## パス参照の更新箇所
- `deploy-mcp.sh`: `SCRIPT_DIR` 基準は維持。末尾の次手順案内を common 配下のパスに変更。
- `invoke-mcp-file.sh`: ロジックは不変。コメントの公開手順を common 配下に変更。
- `redeploy-all.sh`: `common/localstack` から `localllm/` を 2 階層上として解決し、
  `ai-dq/localstack/deploy.sh` と `ai-dq-mcp/localstack/deploy-mcp.sh` を各ディレクトリで
  実行、API 公開は共有 `deploy-apigw.sh` を呼ぶ構成に変更。

## 規約・互換性
- **`API_ID` / `FUNCTION_NAME` は不変**（`mcpapi`/`mcp-local`, `aidqapi`/`aidq-local`,
  `qeragapi`/`qe-rag-local`）。公開 URL `.../restapis/<API_ID>/local/...` は変わりません。
- したがって **`genai-local/exapps-proxy/apps.json` の変更は不要**
  （`ragApiUrl` / `mcpServers[].url` は API_ID 参照のためパス移動の影響を受けない）。
- `query-expansion-rag` は触っていません。
- CDK 構成（`ai-dq/lib`・`ai-dq/bin`・`cdk.json` 等）は対象外で未変更。

## 動作確認手順（新パス）

```bash
# まとめて再デプロイ
cd genai-ai-api/localllm/common/localstack
bash redeploy-all.sh

# 個別（MCP）
cd ../../ai-dq-mcp/localstack
FUNCTION_NAME=mcp-local bash deploy-mcp.sh
API_ID=mcpapi FUNCTION_NAME=mcp-local bash ../../common/localstack/deploy-apigw.sh

# スモークテスト
curl -s -XPOST 'http://localhost:4566/restapis/mcpapi/local/_user_request_/' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# MCP 単体テスト
cd mcp-lambda && python test_app.py
```

## レビュー観点
- [ ] 旧 `ai-dq/localstack` に MCP/共有スクリプトの実体が残っていない
- [ ] `common/localstack` の3スクリプトが揃っている
- [ ] `redeploy-all.sh` の相対パス解決が新構成で正しい
- [ ] `API_ID` / `FUNCTION_NAME` が不変
- [ ] README 群が新パスを反映
