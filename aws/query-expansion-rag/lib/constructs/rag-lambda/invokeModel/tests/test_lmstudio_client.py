"""
lmstudio_client の変換ロジックの単体テスト。

LMStudio への実際の HTTP 通信はモックし、messages / inferenceConfig の変換と
Bedrock Converse 互換レスポンスへの整形を検証する。
"""

import os
import sys

# invokeModel ディレクトリを import パスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import lmstudio_client  # noqa: E402


def test_bedrock_messages_to_openai_with_system():
    messages = [
        {"role": "user", "content": [{"text": "こんにちは"}]},
    ]
    system = [{"text": "あなたは親切なアシスタントです"}]
    result = lmstudio_client._bedrock_messages_to_openai(messages, system)
    assert result[0] == {"role": "system", "content": "あなたは親切なアシスタントです"}
    assert result[1] == {"role": "user", "content": "こんにちは"}


def test_bedrock_messages_to_openai_multiple_text_blocks():
    messages = [
        {"role": "user", "content": [{"text": "A"}, {"text": "B"}]},
    ]
    result = lmstudio_client._bedrock_messages_to_openai(messages, None)
    assert result == [{"role": "user", "content": "AB"}]


def test_inference_config_to_openai():
    cfg = {"maxTokens": 100, "temperature": 0.2, "topP": 0.9, "stopSequences": ["END"]}
    result = lmstudio_client._inference_config_to_openai(cfg)
    assert result == {
        "max_tokens": 100,
        "temperature": 0.2,
        "top_p": 0.9,
        "stop": ["END"],
    }


def test_inference_config_empty():
    assert lmstudio_client._inference_config_to_openai(None) == {}
    assert lmstudio_client._inference_config_to_openai({}) == {}


def test_to_bedrock_converse_response():
    openai_resp = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "こんにちは。"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    result = lmstudio_client._to_bedrock_converse_response(openai_resp)
    assert result["output"]["message"]["content"][0]["text"] == "こんにちは。"
    assert result["stopReason"] == "end_turn"
    assert result["usage"] == {
        "inputTokens": 10,
        "outputTokens": 5,
        "totalTokens": 15,
    }


def test_to_bedrock_converse_response_length_finish():
    openai_resp = {
        "choices": [{"message": {"content": "..."}, "finish_reason": "length"}],
        "usage": {},
    }
    result = lmstudio_client._to_bedrock_converse_response(openai_resp)
    assert result["stopReason"] == "max_tokens"
    assert result["usage"] == {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}


def test_looks_like_embedding():
    assert lmstudio_client._looks_like_embedding("text-embedding-nomic")
    assert lmstudio_client._looks_like_embedding("bge-m3")
    assert not lmstudio_client._looks_like_embedding("qwen2.5-7b-instruct")


def test_resolve_chat_model_env_override(monkeypatch):
    monkeypatch.setenv("LMSTUDIO_CHAT_MODEL", "my-chat-model")
    assert lmstudio_client.resolve_chat_model() == "my-chat-model"


def test_converse_response_shape_is_processable():
    # process_kb_response が期待する citations 構造のスモークテスト
    from services.kb_response_processor import process_kb_response

    fake = {
        "output": {"text": "回答"},
        "citations": [
            {
                "generatedResponsePart": {"textResponsePart": {"text": "回答"}},
                "retrievedReferences": [
                    {
                        "content": {"text": "抜粋"},
                        "metadata": {"file_name": "a.md", "url": "https://x"},
                    }
                ],
            }
        ],
    }
    kb = process_kb_response(fake)
    assert kb.citations[0].text == "回答"
    assert kb.citations[0].metadata[0].file_name == "a.md"
