from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent.logging_config import get_logger
from agent.models import AgentResult, ParsedData

logger = get_logger(__name__)


class Orchestrator:
    def __init__(self, llm_client=None):
        from agent.catalog.catalog_generator import CatalogGenerator
        from agent.checker.csv_checker import CSVChecker
        from agent.parser.csv_parser import CSVParser

        self._parser = CSVParser()
        self._checker = CSVChecker()
        self._catalog_gen = CatalogGenerator(llm_client=llm_client)

    async def run(self, file_path: str, questions: list[str] | None = None) -> AgentResult:
        logger.info(f"Orchestrator.run: file={file_path}, questions={questions}")

        parsed: ParsedData = self._parser.parse(file_path)
        check_results = self._checker.check(parsed)

        file_info = {
            "file_path": parsed.file_path,
            "file_type": parsed.file_type,
            "processed_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
            "encoding": parsed.encoding,
        }

        catalog_outputs_dict = {}
        errors = []

        try:
            metadata, outputs, catalog_errors = await self._catalog_gen.generate(parsed)
            errors.extend(catalog_errors)

            def path_to_str(p: Path) -> str:
                return str(p)

            catalog_outputs_dict[metadata.table_name] = {
                "catalog_md": path_to_str(outputs.catalog_md),
                "datahub_jsonld": path_to_str(outputs.datahub_jsonld),
                "openmetadata_yaml": path_to_str(outputs.openmetadata_yaml),
                "semantic_view_sql": path_to_str(outputs.semantic_view_sql),
                "materialized_view_sql": path_to_str(outputs.materialized_view_sql),
            }
        except Exception as e:
            logger.error(f"Catalog generation error: {e}")
            errors.append(f"\u30ab\u30bf\u30ed\u30b0\u751f\u6210\u30a8\u30e9\u30fc: {e}")

        textsql_comparison = []
        if questions:
            try:
                textsql_comparison = await self._run_textsql(
                    parsed, catalog_outputs_dict, questions
                )
            except Exception as e:
                logger.error(f"Text-to-SQL error: {e}")
                errors.append(f"Text-to-SQL \u30a8\u30e9\u30fc: {e}")

        if errors:
            file_info["errors"] = errors

        result = AgentResult(
            file_info=file_info,
            check_results=check_results,
            catalog_outputs=catalog_outputs_dict,
            textsql_comparison=textsql_comparison,
        )

        return result

    async def _run_textsql(self, parsed: ParsedData, catalog_outputs: dict, questions: list[str]):
        from agent.textsql.comparison import ComparisonRunner
        from agent.textsql.sql_evaluator import SQLEvaluator
        from agent.textsql.sql_generator import SQLGenerator
        from agent.textsql.sqlite_manager import SQLiteManager

        table_name = list(catalog_outputs.keys())[0] if catalog_outputs else "table"
        metadata_json: str | None = None
        if catalog_outputs:
            openmetadata_path = catalog_outputs[table_name].get("openmetadata_yaml", "")
            if openmetadata_path:
                try:
                    import yaml

                    with open(openmetadata_path) as f:
                        data = yaml.safe_load(f)
                    if data is not None:
                        metadata_json = json.dumps(data)
                except Exception as e:
                    logger.warning(f"Failed to load openmetadata for textsql: {e}")

        sqlite_mgr = SQLiteManager()
        schema_ddl = sqlite_mgr.load(parsed.df, table_name)

        generator = SQLGenerator()
        evaluator = SQLEvaluator()
        runner = ComparisonRunner(sqlite_mgr, generator, evaluator)

        results = []
        for question in questions:
            result = await runner.compare(question, schema_ddl, metadata_json, table_name)
            results.append(result)

        return results
