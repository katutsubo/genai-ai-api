from pathlib import Path

from agent.models import TableMetadata


def _sql_str(value: str) -> str:
    """Escape single quotes for use inside SQL single-quoted string literals."""
    return value.replace("'", "''")


class SemanticViewGenerator:
    def generate(self, meta: TableMetadata, output_path: Path) -> None:
        view_name = f"{meta.table_name}_semantic"
        cols = ", ".join(f'"{c.name}"' for c in meta.columns)

        desc = _sql_str(f"{meta.description_ja} / {meta.description_en}")
        lines = [
            f"-- Semantic view for {meta.table_name}",
            f"-- {meta.description_ja} / {meta.description_en}",
            f"CREATE OR REPLACE VIEW {view_name} AS",
            f"SELECT {cols}",
            f"FROM {meta.table_name};",
            "",
            f"COMMENT ON VIEW {view_name} IS '{desc}';",
            "",
        ]

        for col in meta.columns:
            hint = ""
            if col.is_primary_key:
                hint = " [PK]"
            elif col.is_foreign_key and col.foreign_key_ref:
                hint = f" [FK -> {col.foreign_key_ref}]"
            col_desc = _sql_str(f"{col.description_ja} / {col.description_en}{hint}")
            lines.append(f'COMMENT ON COLUMN {view_name}."{col.name}" IS \'{col_desc}\';')

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
