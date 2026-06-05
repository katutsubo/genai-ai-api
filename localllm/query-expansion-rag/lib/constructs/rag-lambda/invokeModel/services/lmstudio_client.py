"""
LMStudio (OpenAI互換 API) を Bedrock クライアントとしてダックタイピングで提供するアダプタ。

USE_LOCAL_LLM=true のとき、`services.aws_clients` がこのモジュールの
`LMStudioBedrockRuntime` / `LMStudioBedrockAgentRuntime` を返すことで、
既存のコア処理 (converse_helper.py / kb_retrieve_and_rating.py 等) を
変更せずに LMStudio へ推論を委譲できる。

設計方針:
- 追加の外部依存を避けるため HTTP 通信は標準ライブラリ urllib を使用する。
- モデル名は LMStudio の GET /v1/models から動的に取得する
  (環境変数で明示指定された場合はそちらを優先)。
- Bedrock 固有のモデルID (anthropic.* / amazon.* / jp.* など) が渡されても
  無視し、LMStudio で実際に利用可能なモデルへ置き換える。
- ただし呼び出し側 (画面のモデル選択) が LMStudio の実在モデル名
  (例: qwen3.5-9b-mtp) を渡した場合は、それを最優先で使用する。

主な環境変数:
- LMSTUDIO_BASE_URL       : 例 http://host.docker.internal:1234/v1 (既定)
- LMSTUDIO_API_KEY        : OpenAI互換のダミーキー (既定: lm-studio)
- LMSTUDIO_CHAT_MODEL     : chat 用モデルIDを固定したい場合に指定
- LMSTUDIO_EMBEDDING_MODEL: embedding 用モデルIDを固定したい場合に指定
- LMSTUDIO_TIMEOUT        : HTTP タイムアウト秒 (既定: 120)
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from typing import Any

from aws_lambda_powertools import Logger

logger = Logger(child=True)


def _base_url() -> str:
    url = os.environ.get("LMSTUDIO_BASE_URL", "http://host.docker.internal:1234/v1")
    return url.rstrip("/")


def _api_key() -> str:
    return os.environ.get("LMSTUDIO_API_KEY", "lm-studio")


def _timeout() -> float:
    try:
        return float(os.environ.get("LMSTUDIO_TIMEOUT", "120"))
    except (TypeError, ValueError):
        return 120.0


def _http_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """OpenAI互換エンドポイントへ POST し、JSON を返す。"""
    url = f"{_base_url()}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {_api_key()}")
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        logger.error(f"LMStudio HTTP error {e.code} for {url}: {detail}")
        raise
    except urllib.error.URLError as e:
        logger.error(f"LMStudio connection error for {url}: {e}")
        raise


def _http_get(path: str) -> dict[str, Any]:
    url = f"{_base_url()}{path}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {_api_key()}")
    with urllib.request.urlopen(req, timeout=_timeout()) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


# ---- モデル名の動的取得 (キャッシュ付き) ----
_model_cache: dict[str, Any] = {"ids": None}


def list_models() -> list[str]:
    """LMStudio の GET /v1/models から利用可能なモデルID一覧を取得する。"""
    if _model_cache["ids"] is not None:
        return _model_cache["ids"]
    try:
        data = _http_get("/models")
        ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to list LMStudio models, falling back to empty list: {e}")
        ids = []
    _model_cache["ids"] = ids
    logger.debug(f"LMStudio available models: {ids}")
    return ids


def _looks_like_embedding(model_id: str) -> bool:
    lowered = model_id.lower()
    return any(token in lowered for token in ("embed", "bge", "e5", "gte"))


def _is_bedrock_model_id(model_id: str) -> bool:
    """Bedrock 固有のモデルID (anthropic.* / amazon.* / jp.* 等) かどうかを判定する。

    これらは LMStudio には存在しないため、無視して resolve_chat_model() の
    自動解決に委ねる。逆に LMStudio のローカルモデル名
    (例: qwen3.5-9b-mtp) はそのまま使う。
    """
    lowered = (model_id or "").lower()
    bedrock_prefixes = (
        "anthropic.",
        "amazon.",
        "cohere.",
        "meta.",
        "mistral.",
        "ai21.",
        "us.",
        "eu.",
        "jp.",
        "apac.",
        "global.",
    )
    return lowered.startswith(bedrock_prefixes)


def resolve_chat_model(requested_model_id: str | None = None) -> str:
    """chat 用モデルIDを解決する。

    優先順位:
      1. 呼び出し側 (画面のモデル選択) から渡された requested_model_id
         (Bedrock固有IDでない実在モデル名) を最優先で使用する。
      2. 環境変数 LMSTUDIO_CHAT_MODEL (運用上の固定指定)。
      3. LMStudio の /v1/models から embedding 以外を自動選択。
    """
    # 1. 呼び出し側が具体的なローカルモデル名を指定していれば最優先で尊重する
    if requested_model_id and not _is_bedrock_model_id(requested_model_id):
        return requested_model_id

    # 2. 環境変数による固定指定
    explicit = os.environ.get("LMSTUDIO_CHAT_MODEL")
    if explicit:
        return explicit

    # 3. /v1/models から embedding っぽくないモデルを優先選択
    ids = list_models()
    for mid in ids:
        if not _looks_like_embedding(mid):
            return mid
    if ids:
        return ids[0]
    # /v1/models が空でも LMStudio はロード済みモデルに解決してくれることがある
    return "local-model"


def resolve_embedding_model() -> str:
    """embedding 用モデルIDを解決する。"""
    explicit = os.environ.get("LMSTUDIO_EMBEDDING_MODEL")
    if explicit:
        return explicit
    ids = list_models()
    for mid in ids:
        if _looks_like_embedding(mid):
            return mid
    # 見つからない場合は chat モデルにフォールバック (LMStudio が拒否する場合あり)
    return resolve_chat_model()


def _bedrock_messages_to_openai(
    messages: list[dict[str, Any]], system: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Bedrock Converse 形式の messages を OpenAI chat 形式へ変換する。"""
    openai_messages: list[dict[str, Any]] = []

    if system:
        system_text = "".join(block.get("text", "") for block in system if isinstance(block, dict))
        if system_text:
            openai_messages.append({"role": "system", "content": system_text})

    for message in messages:
        role = message.get("role", "user")
        content_blocks = message.get("content", [])
        text_parts: list[str] = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if "text" in block:
                text_parts.append(block["text"])
            # image / document など非テキストブロックはローカルLLMでは無視
        openai_messages.append({"role": role, "content": "".join(text_parts)})

    return openai_messages


def _inference_config_to_openai(inference_config: dict[str, Any] | None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if not inference_config:
        return params
    if "maxTokens" in inference_config:
        params["max_tokens"] = inference_config["maxTokens"]
    if "temperature" in inference_config:
        params["temperature"] = inference_config["temperature"]
    if "topP" in inference_config:
        params["top_p"] = inference_config["topP"]
    if "stopSequences" in inference_config:
        params["stop"] = inference_config["stopSequences"]
    return params


def _to_bedrock_converse_response(openai_resp: dict[str, Any]) -> dict[str, Any]:
    """OpenAI chat.completions レスポンスを Bedrock Converse 形式へ整形する。"""
    choices = openai_resp.get("choices", [])
    content_text = ""
    stop_reason = "end_turn"
    if choices:
        message = choices[0].get("message", {})
        content_text = message.get("content") or ""
        finish = choices[0].get("finish_reason")
        if finish == "length":
            stop_reason = "max_tokens"
        elif finish == "stop":
            stop_reason = "end_turn"

    usage = openai_resp.get("usage", {}) or {}
    input_tokens = usage.get("prompt_tokens", 0) or 0
    output_tokens = usage.get("completion_tokens", 0) or 0
    total_tokens = usage.get("total_tokens", input_tokens + output_tokens) or 0

    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": content_text}],
            }
        },
        "stopReason": stop_reason,
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": total_tokens,
        },
    }


class LMStudioBedrockRuntime:
    """boto3 bedrock-runtime の `converse` を LMStudio で代替するアダプタ。"""

    def converse(
        self,
        *,
        modelId: str | None = None,  # noqa: N803 (Bedrock API のシグネチャに合わせる)
        messages: list[dict[str, Any]],
        inferenceConfig: dict[str, Any] | None = None,  # noqa: N803
        system: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # 画面で選択された modelId が LMStudio の実在モデル名なら尊重し、
        # Bedrock 固有ID (anthropic.* 等) の場合のみ自動解決へフォールバックする。
        model = resolve_chat_model(modelId)
        if modelId and modelId != model:
            logger.debug(f"Requested modelId '{modelId}' -> using LMStudio model '{model}'")
        else:
            logger.debug(f"Using LMStudio model '{model}'")

        payload: dict[str, Any] = {
            "model": model,
            "messages": _bedrock_messages_to_openai(messages, system),
            "stream": False,
        }
        payload.update(_inference_config_to_openai(inferenceConfig))

        logger.debug(f"Invoking LMStudio chat.completions with model: {model}")
        openai_resp = _http_post("/chat/completions", payload)
        return _to_bedrock_converse_response(openai_resp)


def embed(texts: list[str]) -> list[list[float]]:
    """LMStudio /v1/embeddings で埋め込みを取得する。"""
    if not texts:
        return []
    payload = {"model": resolve_embedding_model(), "input": texts}
    resp = _http_post("/embeddings", payload)
    items = sorted(resp.get("data", []), key=lambda x: x.get("index", 0))
    return [item["embedding"] for item in items]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _load_local_documents() -> list[dict[str, Any]]:
    """ローカル簡易KB用のドキュメントを読み込む。

    LOCAL_KB_DOCS_PATH (JSON) で指定されたファイルから読み込む。
    形式: [{"text": "...", "file_name": "...", "url": "..."}, ...]
    指定が無い / 読めない場合は空リストを返す (=直接生成にフォールバック)。
    """
    path = os.environ.get("LOCAL_KB_DOCS_PATH")
    if not path:
        # Lambda パッケージ同梱の既定パスも探す
        default_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "local_kb_docs.json")
        path = default_path if os.path.exists(default_path) else None
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            docs = json.load(f)
        if isinstance(docs, list):
            return [d for d in docs if isinstance(d, dict) and d.get("text")]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to load local KB docs from {path}: {e}")
    return []


class LMStudioBedrockAgentRuntime:
    """boto3 bedrock-agent-runtime の `retrieve_and_generate` を LMStudio で代替するアダプタ。

    本物の Knowledge Base が無いローカル環境向けに、簡易的な
    embedding ベース検索 + LMStudio 生成を行い、Bedrock の
    retrieve_and_generate 互換レスポンス (citations 構造) を返す。
    ドキュメントが無い場合は空 citations + 直接生成にフォールバックする。
    """

    def retrieve_and_generate(
        self,
        *,
        retrieveAndGenerateConfiguration: dict[str, Any],  # noqa: N803
        input: dict[str, Any],  # noqa: A002 (Bedrock API のシグネチャに合わせる)
        **kwargs: Any,
    ) -> dict[str, Any]:
        query = input.get("text", "")
        kb_config = retrieveAndGenerateConfiguration.get("knowledgeBaseConfiguration", {})
        retrieval_config = kb_config.get("retrievalConfiguration", {})
        num_results = (
            retrieval_config.get("vectorSearchConfiguration", {}).get("numberOfResults", 5)
        )

        # 画面で選択された modelId を取り出し、生成時に尊重する
        # (modelArn 末尾の foundation-model/<id> または inference-profile/<id> から抽出)
        requested_model_id = None
        model_arn = kb_config.get("modelArn")
        if isinstance(model_arn, str) and model_arn:
            requested_model_id = model_arn.split("/")[-1]

        docs = _load_local_documents()
        top_docs: list[dict[str, Any]] = []
        if docs:
            try:
                query_vec = embed([query])[0]
                doc_texts = [d["text"] for d in docs]
                doc_vecs = embed(doc_texts)
                scored = [
                    (self_score := _cosine(query_vec, dv), d)
                    for dv, d in zip(doc_vecs, docs)
                ]
                scored.sort(key=lambda x: x[0], reverse=True)
                top_docs = [d for _, d in scored[:num_results]]
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Local KB retrieval failed, falling back to direct generation: {e}")
                top_docs = []

        # 生成: 取得した抜粋をコンテキストに LMStudio で回答
        context = "\n\n".join(
            f"[抜粋{i + 1}] {d['text']}" for i, d in enumerate(top_docs)
        )
        if context:
            user_text = (
                f"以下の検索結果のみを根拠に、日本語で質問に答えてください。\n\n"
                f"# 検索結果\n{context}\n\n# 質問\n{query}"
            )
        else:
            user_text = query

        runtime = LMStudioBedrockRuntime()
        converse_resp = runtime.converse(
            modelId=requested_model_id,
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={"temperature": 0, "maxTokens": 2048},
        )
        generated_text = (
            converse_resp["output"]["message"]["content"][0]["text"]
        )

        retrieved_references = [
            {
                "content": {"text": d["text"]},
                "metadata": {
                    "file_name": d.get("file_name"),
                    "url": d.get("url"),
                },
            }
            for d in top_docs
        ]

        return {
            "output": {"text": generated_text},
            "citations": [
                {
                    "generatedResponsePart": {
                        "textResponsePart": {"text": generated_text}
                    },
                    "retrievedReferences": retrieved_references,
                }
            ],
        }
