import pandas as pd
import pytest
from agent.models import ColumnMetadata, ParsedData, TableMetadata


def make_parsed():
    df = pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})
    return ParsedData(file_path="test.csv", file_type="csv", df=df, encoding="utf-8")


def make_table_metadata():
    return TableMetadata(
        table_name="test",
        description_ja="テストテーブル",
        description_en="Test table",
        domain="test.domain",
        owner="test_owner",
        tags=["test"],
        columns=[
            ColumnMetadata(
                name="id",
                description_ja="識別子",
                description_en="Identifier",
                data_type="int64",
                is_nullable=False,
                is_primary_key=True,
                is_foreign_key=False,
                foreign_key_ref=None,
                tags=[],
            ),
            ColumnMetadata(
                name="name",
                description_ja="名前",
                description_en="Name",
                data_type="object",
                is_nullable=True,
                is_primary_key=False,
                is_foreign_key=False,
                foreign_key_ref=None,
                tags=[],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_metadata_contains_ja_and_en():
    meta = make_table_metadata()
    assert meta.description_ja
    assert meta.description_en
    for col in meta.columns:
        assert col.description_ja
        assert col.description_en


@pytest.mark.asyncio
async def test_datahub_jsonld_contains_dcat_dublin_spdx(tmp_path):
    from agent.catalog.datahub_exporter import DatahubExporter

    meta = make_table_metadata()
    exporter = DatahubExporter()
    out = tmp_path / "datahub_mce.jsonld"
    exporter.export(meta, out)
    content = out.read_text()
    assert "dcat" in content.lower() or "@context" in content
    assert (
        "dcterms" in content.lower()
        or "dublin" in content.lower()
        or "dc:" in content.lower()
        or "dct:" in content.lower()
    )
    assert "spdx" in content.lower() or "license" in content.lower()


@pytest.mark.asyncio
async def test_openmetadata_yaml_contains_required_fields(tmp_path):
    import yaml
    from agent.catalog.openmetadata_exporter import OpenMetadataExporter

    meta = make_table_metadata()
    exporter = OpenMetadataExporter()
    out = tmp_path / "openmetadata.yaml"
    exporter.export(meta, out)
    data = yaml.safe_load(out.read_text())
    assert "name" in data
    assert "description" in data
    assert "columns" in data


@pytest.mark.asyncio
async def test_semantic_view_ddl_has_comments(tmp_path):
    from agent.catalog.semantic_view import SemanticViewGenerator

    meta = make_table_metadata()
    gen = SemanticViewGenerator()
    out = tmp_path / "semantic_view.sql"
    gen.generate(meta, out)
    content = out.read_text()
    assert "VIEW" in content
    assert "COMMENT ON" in content


@pytest.mark.asyncio
async def test_materialized_view_has_refresh_comment(tmp_path):
    from agent.catalog.materialized_view import MaterializedViewGenerator

    meta = make_table_metadata()
    gen = MaterializedViewGenerator()
    out = tmp_path / "materialized_view.sql"
    gen.generate(meta, out)
    content = out.read_text()
    assert "CREATE MATERIALIZED VIEW" in content
    assert "--" in content  # refresh frequency comment
