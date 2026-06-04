from __future__ import annotations

import sqlite3

import pandas as pd


class SQLiteManager:
    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._table_name = None

    def load(self, df: pd.DataFrame, table_name: str) -> str:
        self._table_name = table_name
        df.to_sql(table_name, self._conn, if_exists="replace", index=False)
        cursor = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        )
        row = cursor.fetchone()
        return row[0] if row else f"CREATE TABLE {table_name} (...)"

    def query(self, sql: str) -> list[dict]:
        cursor = self._conn.execute(sql)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def close(self):
        self._conn.close()
