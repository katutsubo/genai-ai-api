import os
import tempfile

import pytest
from agent.parser.csv_parser import CSVParser


@pytest.fixture
def parser():
    return CSVParser()


def write_temp_csv(content: bytes, suffix=".csv") -> str:
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(content)
    f.close()
    return f.name


def test_parse_utf8(parser):
    path = write_temp_csv(b"id,name\n1,Alice\n2,Bob\n")
    try:
        result = parser.parse(path)
        assert result.encoding.lower().replace("-", "") in ("utf8", "utf-8", "ascii")
        assert list(result.df.columns) == ["id", "name"]
        assert len(result.df) == 2
    finally:
        os.unlink(path)


def test_parse_shift_jis(parser):
    path = write_temp_csv("id,名前\n1,テスト\n".encode("shift_jis"))
    try:
        result = parser.parse(path)
        assert (
            "shift" in result.encoding.lower()
            or "sjis" in result.encoding.lower()
            or "932" in result.encoding.lower()
        )
        assert "名前" in result.df.columns
    finally:
        os.unlink(path)


def test_parse_empty_file_raises(parser):
    path = write_temp_csv(b"")
    try:
        with pytest.raises(ValueError, match="empty"):
            parser.parse(path)
    finally:
        os.unlink(path)


def test_parse_truncates_columns_over_max(parser, monkeypatch):
    monkeypatch.setenv("MAX_COLUMNS", "50")
    # reload config
    import importlib

    import agent.config

    importlib.reload(agent.config)
    import agent.parser.csv_parser

    importlib.reload(agent.parser.csv_parser)
    from agent.parser.csv_parser import CSVParser as ReloadedParser

    cols = [f"col{i}" for i in range(100)]
    row = ",".join(["1"] * 100)
    header = ",".join(cols)
    path = write_temp_csv(f"{header}\n{row}\n".encode())
    try:
        p = ReloadedParser()
        result = p.parse(path)
        assert len(result.df.columns) == 50
        assert result.df.columns.tolist() == cols[:50]
    finally:
        os.unlink(path)
