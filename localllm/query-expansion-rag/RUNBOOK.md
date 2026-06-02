# Query Expansion RAG を開発環境（LocalStack + LMStudio）で起動・動作確認する手順

`aws/query-expansion-rag` の RAG Lambda を LocalStack 上で起動し、Bedrock 呼び出しを
LMStudio（OpenAI 互換）へ振り向けて動作確認するための手順です。

## 0. 事前準備（インストール確認）

```bash
# Docker / docker compose
docker --version
docker compose version

# awslocal（無ければ）
pip install awscli-local

# Python3 / pip / zip
python3 --version && pip --version && zip --version
```

## 1. LMStudio を起動（ホスト側）

1. LMStudio を起動し、**チャット用モデルを1つ以上ロード**（埋め込み付きローカルKBを使うなら埋め込みモデルもロード）。
2. 左メニューの **「Developer / Local Server」** で **OpenAI 互換サーバを Start**（既定ポート `1234`）。
3. 疎通確認:

   ```bash
   curl http://localhost:1234/v1/models
   ```

   ここで返る `id` がそのまま使われます（`LMSTUDIO_CHAT_MODEL` 等で固定しない限り自動選択）。

## 2. リポジトリ取得とブランチ切替

```bash
git clone https://github.com/katutsubo/genai-ai-api.git
cd genai-ai-api
git checkout localstack-lmstudio
cd localllm/ai-ready-agent-mvp/localstack
```

## 3. LocalStack 起動 → Lambda デプロイ → 実行

```bash
# LocalStack 起動
docker compose up -d

# 依存インストール → zip → awslocal lambda create-function
./deploy.sh

# サンプル event を直接 invoke
./invoke.sh
```

`./invoke.sh` が Lambda の生レスポンスと、パースした `body`
（`{"outputs": ..., "usageMetadata": ...}`）を表示すれば成功です。

別の質問を試す場合:

```bash
cp event.sample.json my_event.json   # body内のquestionを書き換え
./invoke.sh my_event.json
```

## 4. （任意）単体テスト

```bash
cd ../lib/constructs/rag-lambda/invokeModel
pip install pytest
pytest tests/test_lmstudio_client.py
```

## トラブルシューティング

| 症状 | 原因・対処 |
|---|---|
| Lambda から LMStudio に繋がらない（接続エラー/タイムアウト） | Lambda コンテナ内からは `localhost` 不可。`LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1` を使う（deploy.sh の既定）。Linux では `docker-compose.yml` の `LAMBDA_DOCKER_FLAGS=--add-host=host.docker.internal:host-gateway` が効いているか確認 |
| `awslocal: command not found` | `pip install awscli-local`。または deploy.sh は自動で `aws --endpoint-url=http://localhost:4566` にフォールバック |
| Lambda 実行はされるが回答が空/エラー | LMStudio 側でモデルが未ロード、またはサーバ未起動。`curl http://localhost:1234/v1/models` を確認 |
| ローカルKBの引用が出ない | `local_kb_docs.json` が同梱されているか、埋め込みモデルがロードされているか確認。無ければ直接生成にフォールバック（正常動作） |
| ログを見たい | `docker logs -f qe-rag-localstack`。`LOG_LEVEL=DEBUG`（deploy.sh 既定）で詳細出力 |
| モデルを固定したい | `LMSTUDIO_CHAT_MODEL=... LMSTUDIO_EMBEDDING_MODEL=... ./deploy.sh` |

## 補足

- 再デプロイ（コード変更後）は `./deploy.sh` を再実行すれば `update-function-code` で更新されます。
- 後片付けは `docker compose down`（`./volume` を消すと状態クリア）。
- 実行後の生レスポンスは `response.json` に保存されます。