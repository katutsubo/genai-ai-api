from __future__ import annotations

import json
import os

from agent.llm.litellm_client import LiteLLMClient
from agent.llm.utils import strip_markdown_fence
from agent.logging_config import get_logger
from agent.models import ColumnMetadata, LLMResponse, ParsedData, TableMetadata

logger = get_logger(__name__)

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "../prompts/metadata_generate.txt")


class MetadataGenerator:
    def __init__(self, llm_client=None, model: str | None = None):
        self._llm = llm_client or LiteLLMClient(model=model)

    async def generate(self, parsed: ParsedData) -> TableMetadata:
        table_name = os.path.splitext(os.path.basename(parsed.file_path))[0]
        schema_summary = self._build_schema_summary(parsed)

        with open(_PROMPT_PATH, encoding="utf-8") as f:
            template = f.read()
        prompt = template.replace("{table_name}", table_name).replace(
            "{schema_summary}", schema_summary
        )

        response: LLMResponse = await self._llm.chat(prompt)
        raw = strip_markdown_fence(response.content)
        data = json.loads(raw)
        return self._parse_metadata(data, table_name)

    def _build_schema_summary(self, parsed: ParsedData) -> str:
        df = parsed.df
        lines = [f"行数: {len(df)}", f"カラム数: {len(df.columns)}", ""]
        for col in df.columns:
            dtype = str(df[col].dtype)
            null_count = int(df[col].isnull().sum())
            sample = df[col].dropna().head(3).tolist()
            lines.append(f"- {col} ({dtype}): null={null_count}, sample={sample}")
        return "\n".join(lines)

    def _parse_metadata(self, data: dict, table_name: str) -> TableMetadata:
        columns = []
        for col in data.get("columns", []):
            columns.append(
                ColumnMetadata(
                    name=col.get("name", ""),
                    description_ja=col.get("description_ja", ""),
                    description_en=col.get("description_en", ""),
                    data_type=col.get("data_type", "object"),
                    is_nullable=col.get("is_nullable", True),
                    is_primary_key=col.get("is_primary_key", False),
                    is_foreign_key=col.get("is_foreign_key", False),
                    foreign_key_ref=col.get("foreign_key_ref"),
                    tags=col.get("tags", []),
                )
            )
        return TableMetadata(
            table_name=data.get("table_name", table_name),
            description_ja=data.get("description_ja", ""),
            description_en=data.get("description_en", ""),
            domain=data.get("domain", ""),
            owner=data.get("owner", ""),
            tags=data.get("tags", []),
            columns=columns,
        )
