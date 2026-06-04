from pathlib import Path

import yaml

from agent.models import TableMetadata


class OpenMetadataExporter:
    def export(self, meta: TableMetadata, output_path: Path) -> None:
        doc = {
            "name": meta.table_name,
            "description": f"{meta.description_ja} / {meta.description_en}",
            "tableType": "Regular",
            "databaseSchema": meta.domain,
            "owner": {"name": meta.owner},
            "tags": [{"tagFQN": t} for t in meta.tags],
            "columns": [
                {
                    "name": col.name,
                    "description": f"{col.description_ja} / {col.description_en}",
                    "dataType": col.data_type,
                    "constraint": "PRIMARY_KEY"
                    if col.is_primary_key
                    else ("NOT_NULL" if not col.is_nullable else None),
                    "tags": [{"tagFQN": t} for t in col.tags],
                }
                for col in meta.columns
            ],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(doc, f, allow_unicode=True, default_flow_style=False)
