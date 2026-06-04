from __future__ import annotations

from agent.logging_config import get_logger
from agent.models import ComparisonResult
from agent.textsql.sql_evaluator import SQLEvaluator
from agent.textsql.sql_generator import SQLGenerator
from agent.textsql.sqlite_manager import SQLiteManager

logger = get_logger(__name__)


class ComparisonRunner:
    def __init__(self, sqlite_mgr: SQLiteManager, generator: SQLGenerator, evaluator: SQLEvaluator):
        self._sqlite = sqlite_mgr
        self._generator = generator
        self._evaluator = evaluator

    async def compare(
        self,
        question: str,
        schema_ddl: str,
        metadata_json: str | None,
        table_name: str,
    ) -> ComparisonResult:
        sql_before = await self._generator.generate(question, schema_ddl, metadata_json=None)
        sql_after = await self._generator.generate(
            question, schema_ddl, metadata_json=metadata_json
        )

        result_before: list[dict] = []
        before_failed = False
        try:
            result_before = self._sqlite.query(sql_before)
        except Exception as e:
            logger.warning(f"SQL before execution error: {e}")
            before_failed = True

        result_after: list[dict] = []
        after_failed = False
        try:
            result_after = self._sqlite.query(sql_after)
        except Exception as e:
            logger.warning(f"SQL after execution error: {e}")
            after_failed = True

        score_before, score_after = await self._evaluator.evaluate_pair(
            question,
            sql_before,
            sql_after,
            result_before,
            result_after,
            before_failed=before_failed,
            after_failed=after_failed,
        )

        before_c = score_before.get("correctness", 5)
        after_c = score_after.get("correctness", 5)
        if after_c > before_c:
            verdict = "improved"
        elif after_c < before_c:
            verdict = "degraded"
        else:
            verdict = "same"

        return ComparisonResult(
            question=question,
            sql_before=sql_before,
            sql_after=sql_after,
            result_before=result_before,
            result_after=result_after,
            score_before=score_before,
            score_after=score_after,
            verdict=verdict,
        )
