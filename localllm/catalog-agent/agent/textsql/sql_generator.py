from __future__ import annotations

import os

from agent.llm.litellm_client import LiteLLMClient
from agent.llm.utils import strip_markdown_fence
from agent.logging_config import get_logger

logger = get_logger(__name__)

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "../prompts/sql_generate.txt")


class SQLGenerator:
    def __init__(self, llm_client=None):
        self._llm = llm_client or LiteLLMClient()

    async def generate(self, question: str, schema_ddl: str, metadata_json: str | None) -> str:
        with open(_PROMPT_PATH, encoding="utf-8") as f:
            template = f.read()

        if metadata_json and metadata_json not in ("{}", "null", ""):
            metadata_section = f"メタデータ（カラム説明・FK ヒント付き）:\n{metadata_json}"
        else:
            metadata_section = "（メタデータなし — スキーマのみ使用）"

        prompt = (
            template.replace("{question}", question)
            .replace("{schema_ddl}", schema_ddl)
            .replace("{metadata_section}", metadata_section)
        )

        response = await self._llm.chat(prompt)
        sql = strip_markdown_fence(response.content)
        logger.info(f"Generated SQL: {sql[:200]}")
        return sql.strip()
