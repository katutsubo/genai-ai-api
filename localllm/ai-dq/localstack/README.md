# Query Expansion RAG を LocalStack + LMStudio で動かす（ローカル開発用）

このディレクトリは、`aws/query-expansion-rag` の RAG Lambda を **AWS 実環境ではなく
LocalStack 上**で動かし、内部の **Bedrock 呼び出し（Converse / RetrieveAndGenerate /
Embedding）を LMStudio（OpenAI 互換のローカル LLM）に振り向ける**ための最小構成です。

- API Gateway / WAF / KMS CMEK / OpenSearch Serverless / Cognito は **使いません**。
- `awslocal lambda invoke` で **Lambda を直接叩く**最小トポロジです。
- モデル名は LMStudio の `GET /v1/models` から **動的取得**します（Bedrock 固有 ID に依存しません）。

> **本番（実 Bedrock）には影響しません。** 切り替えは環境変数 `USE_LOCAL_LLM` で行い、
> 未設定（デフォルト）では従来どおり実 Bedrock を呼び出します。

## 仕組み

`services/aws_clients.py` が `USE_LOCAL_LLM=true` のとき、`bedrock_runtime` /
`bedrock_agent_runtime` を LMStudio アダプタ（`services/lmstudio_client.py`）に差し替えます。
シンボル名は同じなので、`converse_helper.py` や `kb_retrieve_and_rating.py` などの
コア処理は **import を変えずにそのまま** 動作します。

| Bedrock 呼び出し | ローカルでの代替 |
|---|---|
| `bedrock_runtime.converse(...)` | LMStudio `POST /v1/chat/completions`（messages/inferenceConfig を OpenAI 形式へ変換し、応答を Bedrock Converse 形式へ整形） |
| `bedrock_agent_runtime.retrieve_and_generate(...)` | ローカル簡易 KB（`/v1/embeddings` でコサイン類似度検索）+ LMStudio 生成 → Bedrock `retrieve_and_generate` 互換レスポンスへ整形 |
| 埋め込みモデル | LMStudio `POST /v1/embeddings` |

## 前提条件

- Docker / Docker Compose
- `awslocal`（`pip install awscli-local`）。無い場合は `aws --endpoint-url=http://localhost:4566` でも可
- Python 3 / pip（依存パッケージの zip 同梱に使用）
- **LMStudio** をホストで起動し、**OpenAI 互換サーバを有効化**（既定ポート `1234`）。
  - チャット用モデルを 1 つ以上ロードしておくこと。
  - 埋め込み（ローカル KB を使う）場合は埋め込みモデルもロードしておくこと。
  - ロード済みモデルの ID が `/v1/models` で返り、そのまま使われます。

## 手順

```bash
cd aws/query-expansion-rag/localstack

# 1. LocalStack 起動
docker compose up -d

# 2. Lambda をデプロイ（依存インストール → zip → awslocal lambda create-function）
./deploy.sh

# 3. 動作確認（API Gateway proxy 形式のサンプル event を直接 invoke）
./invoke.sh
```

`invoke.sh` は `event.sample.json` を送り、Lambda の生レスポンスと
`body`（`{"outputs": ..., "usageMetadata": ...}`）をパースして表示します。

別の質問を試す場合：

```bash
./invoke.sh path/to/your_event.json
```

## ローカル簡易 KB（任意）

`bedrock_agent_runtime.retrieve_and_generate` の代替として、`local_kb_docs.json`
に置いた文書を `/v1/embeddings` で埋め込み、コサイン類似度で上位を取得して回答に使います。

- `local_kb_docs.json` の形式: `[{"text": "...", "file_name": "...", "url": "..."}, ...]`
- ファイルが無い／読み込めない場合は、**空 citations + LMStudio による直接生成**にフォールバックします（落ちません）。
- 参照パスは環境変数 `LOCAL_KB_DOCS_PATH` でも指定できます（未指定時は Lambda パッケージ同梱の `local_kb_docs.json`）。

## 環境変数

`deploy.sh` から Lambda に渡されます。実行前にシェルでエクスポートして上書きできます。

| 変数 | 既定値 | 説明 |
|---|---|---|
| `USE_LOCAL_LLM` | `true`（deploy.sh が設定） | `true` で LMStudio アダプタに切替。未設定／`false` で実 Bedrock |
| `LMSTUDIO_BASE_URL` | `http://host.docker.internal:1234/v1` | Lambda コンテナから見た LMStudio の OpenAI 互換エンドポイント |
| `LMSTUDIO_API_KEY` | `lm-studio` | OpenAI 互換のダミーキー（LMStudio は任意値で可） |
| `LMSTUDIO_CHAT_MODEL` | 空（`/v1/models` から動的取得） | chat 用モデル ID を固定したい場合に指定 |
| `LMSTUDIO_EMBEDDING_MODEL` | 空（`/v1/models` から推定） | embedding 用モデル ID を固定したい場合に指定 |
| `LMSTUDIO_TIMEOUT` | `120` | HTTP タイムアウト秒 |
| `KNOWLEDGE_BASE_ID` | `local-dummy-kb` | コードが要求するダミー値 |
| `KB_NUM_RESULTS` | `5` | ローカル KB 検索の取得件数 |
| `LOCAL_KB_DOCS_PATH` | （同梱 json） | ローカル KB 文書の JSON パス |

> **接続先の注意:** Lambda（LocalStack コンテナ）内からホストの LMStudio に届けるため、
> `localhost` ではなく `http://host.docker.internal:1234/v1` を使います。
> `docker-compose.yml` と `LAMBDA_DOCKER_FLAGS` で `host.docker.internal` を解決できるようにしています。

## テスト

アダプタの変換ロジック（messages / inferenceConfig 変換、Converse 互換レスポンス整形）の
単体テストがあります。

```bash
cd aws/query-expansion-rag/lib/constructs/rag-lambda/invokeModel
pytest tests/test_lmstudio_client.py
```

## 既知の制約

- KB はローカル簡易検索（埋め込みコサイン類似度）であり、本物の Bedrock Knowledge Base の
  メタデータフィルタやランキングを完全再現するものではありません。
- `retrieve_and_generate` は擬似実装です（retrieve→generate を LMStudio で代替）。
- ローカル用 Lambda ランタイムは LocalStack が確実に対応する `python3.12` を使用します
  （本番 CDK は `python3.14`）。
- 添付ファイル（画像・ドキュメントブロック）はローカル LLM ではテキスト以外を無視します。
