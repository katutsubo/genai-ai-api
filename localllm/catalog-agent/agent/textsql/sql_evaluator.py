from __future__ import annotations

import json
import os

from agent.llm.litellm_client import LiteLLMClient
from agent.llm.utils import strip_markdown_fence
from agent.logging_config import get_logger

logger = get_logger(__name__)

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "../prompts/sql_evaluate.txt")


class SQLEvaluator:
    def __init__(self, llm_client=None):
        self._llm = llm_client or LiteLLMClient()

    async def evaluate(
        self,
        question: str,
        sql: str,
        result: list[dict],
        sql_failed: bool = False,
    ) -> dict:
        if sql_failed:
            return {"correctness": 1, "readability": 5, "issues": ["SQL execution failed"]}

        prompt = f"""以下の SQL クエリの品質を評価してください。

質問: {question}
SQL: {sql}
実行結果: {json.dumps(result[:5], ensure_ascii=False)}

以下の JSON 形式でスコアを出力してください:
{{"correctness": 1-10, "readability": 1-10, "issues": []}}

JSON のみを出力してください。"""

        response = await self._llm.chat(prompt)
        raw = strip_markdown_fence(response.content)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"correctness": 5, "readability": 5, "issues": ["スコア解析失敗"]}

    async def evaluate_pair(
        self,
        question: str,
        sql_before: str,
        sql_after: str,
        result_before: list[dict],
        result_after: list[dict],
        before_failed: bool = False,
        after_failed: bool = False,
    ) -> tuple[dict, dict]:
        score_before = await self.evaluate(
            question, sql_before, result_before, sql_failed=before_failed
        )
        score_after = await self.evaluate(
            question, sql_after, result_after, sql_failed=after_failed
        )
        return score_before, score_after
