from pathlib import Path

from agent.models import TableMetadata


class MaterializedViewGenerator:
    def generate(self, meta: TableMetadata, output_path: Path) -> None:
        view_name = f"{meta.table_name}_mv"
        cols = ", ".join(f'"{c.name}"' for c in meta.columns)

        lines = [
            f"-- Materialized view for {meta.table_name}",
            f"-- {meta.description_ja} / {meta.description_en}",
            "-- 推奨リフレッシュ頻度: 日次（データ更新頻度に合わせて調整してください）",
            "-- Recommended refresh frequency: daily (adjust to data update cadence)",
            f"CREATE MATERIALIZED VIEW {view_name} AS",
            f"SELECT {cols}",
            f"FROM {meta.table_name};",
            "",
            f"-- インデックス推奨: CREATE UNIQUE INDEX ON {view_name} (id);",
            f"-- Refresh: REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name};",
        ]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
