import json
from pathlib import Path

from agent.models import TableMetadata


class DatahubExporter:
    def export(self, meta: TableMetadata, output_path: Path) -> None:
        jsonld = {
            "@context": {
                "dcat": "http://www.w3.org/ns/dcat#",
                "dct": "http://purl.org/dc/terms/",
                "dcterms": "http://purl.org/dc/terms/",
                "spdx": "http://spdx.org/rdf/terms#",
                "schema": "http://schema.org/",
                "xsd": "http://www.w3.org/2001/XMLSchema#",
            },
            "@type": "dcat:Dataset",
            "dct:title": meta.table_name,
            "dct:description": meta.description_en,
            "dct:description_ja": meta.description_ja,
            "dct:subject": meta.domain,
            "dct:creator": {"@type": "schema:Organization", "schema:name": meta.owner},
            "dcat:keyword": meta.tags,
            "spdx:licenseDeclared": {"@id": "https://spdx.org/licenses/CC-BY-4.0.html"},
            "dcat:distribution": [],
            "dcat:column": [
                {
                    "@type": "dcat:DatasetDistribution",
                    "schema:name": col.name,
                    "dct:description": col.description_en,
                    "dct:description_ja": col.description_ja,
                    "schema:dataType": col.data_type,
                    "schema:nullable": col.is_nullable,
                    "dcat:isPrimaryKey": col.is_primary_key,
                    "dcat:isForeignKey": col.is_foreign_key,
                    "dcat:foreignKeyRef": col.foreign_key_ref,
                    "dcat:keyword": col.tags,
                }
                for col in meta.columns
            ],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(jsonld, f, ensure_ascii=False, indent=2)
