"""
AWS client singletons for the query-expansion-rag Lambda function.

Clients are initialized once at module import (Lambda cold start).
botocore automatically refreshes IAM credentials before each API call,
so these singletons are safe for long-lived Lambda containers.

ローカル開発 (LocalStack + LMStudio) では、環境変数 USE_LOCAL_LLM=true を
設定することで、Bedrock 呼び出しを LMStudio (OpenAI互換 API) に振り向ける
アダプタへ差し替える。デフォルト (未設定) では従来どおり実 Bedrock を使用する。

bedrock_runtime / bedrock_agent_runtime というシンボル名は維持しているため、
既存のコア処理 (converse_helper.py / kb_retrieve_and_rating.py 等) は
import を変更せずにそのまま動作する。
"""

import os


def _use_local_llm() -> bool:
    return os.environ.get("USE_LOCAL_LLM", "").lower() in ("1", "true", "yes", "on")


if _use_local_llm():
    from services.lmstudio_client import (
        LMStudioBedrockAgentRuntime,
        LMStudioBedrockRuntime,
    )

    bedrock_runtime = LMStudioBedrockRuntime()
    bedrock_agent_runtime = LMStudioBedrockAgentRuntime()
else:
    import boto3

    bedrock_runtime = boto3.client("bedrock-runtime")
    bedrock_agent_runtime = boto3.client("bedrock-agent-runtime")
