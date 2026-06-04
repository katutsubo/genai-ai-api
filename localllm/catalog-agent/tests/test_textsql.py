import json
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from agent.models import LLMResponse


def make_df():
    return pd.DataFrame({"id": [1, 2, 3], "name": ["Alice", "Bob", "Carol"], "score": [90, 80, 95]})


@pytest.mark.asyncio
async def test_sqlite_load_and_query():
    from agent.textsql.sqlite_manager import SQLiteManager

    df = make_df()
    mgr = SQLiteManager()
    schema_ddl = mgr.load(df, "test_table")
    assert "CREATE TABLE" in schema_ddl
    results = mgr.query("SELECT name FROM test_table WHERE score > 85")
    names = [r["name"] for r in results]
    assert "Alice" in names
    assert "Carol" in names
    assert "Bob" not in names


@pytest.mark.asyncio
async def test_sql_generator_before_and_after():
    from agent.textsql.sql_generator import SQLGenerator

    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(
        return_value=LLMResponse(
            content="SELECT name FROM test_table ORDER BY score DESC LIMIT 1", model="chat"
        )
    )

    gen = SQLGenerator(llm_client=mock_llm)
    schema_ddl = "CREATE TABLE test_table (id INT, name TEXT, score INT);"
    sql_before = await gen.generate(
        question="最もスコアが高い人は？",
        schema_ddl=schema_ddl,
        metadata_json=None,
    )
    sql_after = await gen.generate(
        question="最もスコアが高い人は？",
        schema_ddl=schema_ddl,
        metadata_json='{"name": "test", "description": "テスト"}',
    )
    assert "SELECT" in sql_before.upper()
    assert "SELECT" in sql_after.upper()


@pytest.mark.asyncio
async def test_sql_evaluator_returns_scores():
    from agent.textsql.sql_evaluator import SQLEvaluator

    score_response = json.dumps(
        {
            "correctness": 8,
            "readability": 7,
            "issues": [],
        }
    )
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value=LLMResponse(content=score_response, model="chat"))

    evaluator = SQLEvaluator(llm_client=mock_llm)
    score = await evaluator.evaluate(
        question="最もスコアが高い人は？",
        sql="SELECT name FROM t ORDER BY score DESC LIMIT 1",
        result=[{"name": "Carol"}],
    )
    assert "correctness" in score
    assert "readability" in score
    assert isinstance(score["correctness"], int)


@pytest.mark.asyncio
async def test_comparison_verdict_and_no_auto_apply():
    from agent.textsql.comparison import ComparisonRunner
    from agent.textsql.sql_evaluator import SQLEvaluator
    from agent.textsql.sql_generator import SQLGenerator
    from agent.textsql.sqlite_manager import SQLiteManager

    df = make_df()
    sqlite_mgr = SQLiteManager()
    schema_ddl = sqlite_mgr.load(df, "test_table")

    sql_response = "SELECT name FROM test_table ORDER BY score DESC LIMIT 1"
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value=LLMResponse(content=sql_response, model="chat"))

    score_before = json.dumps({"correctness": 6, "readability": 6, "issues": []})
    score_after = json.dumps({"correctness": 9, "readability": 9, "issues": []})
    eval_llm = MagicMock()
    eval_llm.chat = AsyncMock(
        side_effect=[
            LLMResponse(content=score_before, model="chat"),
            LLMResponse(content=score_after, model="chat"),
        ]
    )

    gen = SQLGenerator(llm_client=mock_llm)
    evaluator = SQLEvaluator(llm_client=eval_llm)
    runner = ComparisonRunner(sqlite_mgr, gen, evaluator)

    result = await runner.compare(
        question="最もスコアが高い人は？",
        schema_ddl=schema_ddl,
        metadata_json='{"name": "test"}',
        table_name="test_table",
    )

    assert result.verdict in ("improved", "same", "degraded")
    assert result.sql_before
    assert result.sql_after
    # SQL は表示のみ — DB への自動適用がないことを確認（テーブルは変更されていない）
    rows = sqlite_mgr.query("SELECT COUNT(*) as cnt FROM test_table")
    assert rows[0]["cnt"] == 3


@pytest.mark.asyncio
async def test_after_score_gte_before_score():
    from agent.textsql.comparison import ComparisonRunner
    from agent.textsql.sql_evaluator import SQLEvaluator
    from agent.textsql.sql_generator import SQLGenerator
    from agent.textsql.sqlite_manager import SQLiteManager

    df = make_df()
    sqlite_mgr = SQLiteManager()
    schema_ddl = sqlite_mgr.load(df, "test_table")

    sql_response = "SELECT name FROM test_table ORDER BY score DESC LIMIT 1"
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value=LLMResponse(content=sql_response, model="chat"))

    score_before = json.dumps({"correctness": 6, "readability": 6, "issues": []})
    score_after = json.dumps({"correctness": 9, "readability": 9, "issues": []})
    eval_llm = MagicMock()
    eval_llm.chat = AsyncMock(
        side_effect=[
            LLMResponse(content=score_before, model="chat"),
            LLMResponse(content=score_after, model="chat"),
        ]
    )

    gen = SQLGenerator(llm_client=mock_llm)
    evaluator = SQLEvaluator(llm_client=eval_llm)
    runner = ComparisonRunner(sqlite_mgr, gen, evaluator)

    result = await runner.compare(
        question="最もスコアが高い人は？",
        schema_ddl=schema_ddl,
        metadata_json='{"name": "test"}',
        table_name="test_table",
    )
    assert result.score_after["correctness"] >= result.score_before["correctness"]
