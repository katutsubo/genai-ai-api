import json

import httpx

from agent.config import config
from agent.llm.base_llm import BaseLLM
from agent.logging_config import get_logger
from agent.models import LLMResponse

logger = get_logger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LLMParseError(Exception):
    pass


class LiteLLMClient(BaseLLM):
    def __init__(self):
        self.base_url = config.LITELLM_BASE_URL
        self.api_key = config.LITELLM_API_KEY
        self.model = config.LLM_MODEL

    async def chat(self, prompt: str) -> LLMResponse:
        logger.info(json.dumps({"event": "llm_request", "prompt_length": len(prompt)}))

        last_error = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{self.base_url}/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "model": self.model,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    )
                    response.raise_for_status()
            except httpx.ConnectError as e:
                last_error = e
                logger.warning(
                    json.dumps(
                        {"event": "llm_connection_error", "attempt": attempt + 1, "error": str(e)}
                    )
                )
                continue
            except httpx.HTTPStatusError as e:
                if e.response.status_code in _RETRYABLE_STATUS:
                    last_error = e
                    logger.warning(
                        json.dumps(
                            {
                                "event": "llm_http_error",
                                "attempt": attempt + 1,
                                "status": e.response.status_code,
                            }
                        )
                    )
                    continue
                logger.error(
                    json.dumps({"event": "llm_http_error_fatal", "status": e.response.status_code})
                )
                raise

            try:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                model = data.get("model", self.model)
                logger.info(
                    json.dumps(
                        {"event": "llm_response", "model": model, "content_length": len(content)}
                    )
                )
                return LLMResponse(content=content, model=model)
            except Exception as e:
                last_error = e
                logger.warning(
                    json.dumps(
                        {"event": "llm_parse_error", "attempt": attempt + 1, "error": str(e)}
                    )
                )
                continue

        raise LLMParseError(f"LLM request failed after 3 attempts: {last_error}")
