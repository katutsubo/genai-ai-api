from __future__ import annotations

import os
from pathlib import Path

from agent.catalog.datahub_exporter import DatahubExporter
from agent.catalog.materialized_view import MaterializedViewGenerator
from agent.catalog.metadata_generator import MetadataGenerator
from agent.catalog.openmetadata_exporter import OpenMetadataExporter
from agent.catalog.semantic_view import SemanticViewGenerator
from agent.config import config
from agent.llm.litellm_client import LLMParseError
from agent.logging_config import get_logger
from agent.models import CatalogOutputs, ParsedData, TableMetadata

logger = get_logger(__name__)


class CatalogGenerator:
    def __init__(self, llm_client=None, model: str | None = None):
        self._meta_gen = MetadataGenerator(llm_client=llm_client, model=model)
        self._datahub = DatahubExporter()
        self._openmetadata = OpenMetadataExporter()
        self._semantic = SemanticViewGenerator()
        self._materialized = MaterializedViewGenerator()

    async def generate(self, parsed: ParsedData) -> tuple[TableMetadata, CatalogOutputs, list[str]]:
        errors = []
        table_name = os.path.splitext(os.path.basename(parsed.file_path))[0]
        out_dir = Path(config.OUTPUT_DIR) / "catalog" / table_name
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            metadata = await self._meta_gen.generate(parsed)
        except (LLMParseError, ConnectionError, Exception) as e:
            logger.error(f"Metadata generation failed: {e}")
            errors.append(f"メタデータ生成失敗: {e}")
            from agent.models import ColumnMetadata

            metadata = TableMetadata(
                table_name=table_name,
                description_ja="",
                description_en="",
                domain="",
                owner="",
                tags=[],
                columns=[
                    ColumnMetadata(
                        name=col,
                        description_ja="",
                        description_en="",
                        data_type=str(parsed.df[col].dtype),
                        is_nullable=bool(parsed.df[col].isnull().any()),
                        is_primary_key=False,
                        is_foreign_key=False,
                        foreign_key_ref=None,
                        tags=[],
                    )
                    for col in parsed.df.columns
                ],
            )

        catalog_md = out_dir / "catalog.md"
        datahub_jsonld = out_dir / "datahub_mce.jsonld"
        openmetadata_yaml = out_dir / "openmetadata.yaml"
        semantic_view_sql = out_dir / "semantic_view.sql"
        materialized_view_sql = out_dir / "materialized_view.sql"

        catalog_md.write_text(self._build_catalog_md(metadata), encoding="utf-8")

        try:
            self._datahub.export(metadata, datahub_jsonld)
        except Exception as e:
            errors.append(f"DataHub エクスポート失敗: {e}")
            datahub_jsonld.write_text("{}")

        try:
            self._openmetadata.export(metadata, openmetadata_yaml)
        except Exception as e:
            errors.append(f"OpenMetadata エクスポート失敗: {e}")
            openmetadata_yaml.write_text("")

        try:
            self._semantic.generate(metadata, semantic_view_sql)
        except Exception as e:
            errors.append(f"セマンティックビュー生成失敗: {e}")
            semantic_view_sql.write_text("")

        try:
            self._materialized.generate(metadata, materialized_view_sql)
        except Exception as e:
            errors.append(f"マテリアライズドビュー生成失敗: {e}")
            materialized_view_sql.write_text("")

        outputs = CatalogOutputs(
            catalog_md=catalog_md,
            datahub_jsonld=datahub_jsonld,
            openmetadata_yaml=openmetadata_yaml,
            semantic_view_sql=semantic_view_sql,
            materialized_view_sql=materialized_view_sql,
        )

        return metadata, outputs, errors

    def _build_catalog_md(self, meta: TableMetadata) -> str:
        lines = [
            f"# {meta.table_name}",
            "",
            f"**説明（日本語）**: {meta.description_ja}",
            f"**Description (English)**: {meta.description_en}",
            f"**ドメイン**: {meta.domain}",
            f"**オーナー**: {meta.owner}",
            f"**タグ**: {', '.join(meta.tags)}",
            "",
            "## カラム一覧",
            "",
            "| カラム名 | 型 | 説明（日本語） | Description (EN) | PK | FK |",
            "|----------|-----|----------------|-------------------|----|----|",
        ]
        for col in meta.columns:
            pk = "✓" if col.is_primary_key else ""
            fk = col.foreign_key_ref or ("✓" if col.is_foreign_key else "")
            lines.append(
                f"| {col.name} | {col.data_type} | {col.description_ja} | {col.description_en} | {pk} | {fk} |"
            )
        return "\n".join(lines) + "\n"
