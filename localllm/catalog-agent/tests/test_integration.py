import json

import pytest
from agent.models import LLMResponse
from httpx import ASGITransport, AsyncClient
from main import app


def make_csv_bytes(content: str = "id,name,score\n1,Alice,90\n2,Bob,80\n") -> bytes:
    return content.encode("utf-8")


@pytest.mark.asyncio
async def test_full_pipeline_mock_llm(monkeypatch):
    metadata_json = json.dumps(
        {
            "table_name": "test",
            "description_ja": "テスト",
            "description_en": "Test",
            "domain": "test",
            "owner": "owner",
            "tags": [],
            "columns": [
                {
                    "name": "id",
                    "description_ja": "ID",
                    "description_en": "ID",
                    "data_type": "int64",
                    "is_nullable": False,
                    "is_primary_key": True,
                    "is_foreign_key": False,
                    "foreign_key_ref": None,
                    "tags": [],
                },
                {
                    "name": "name",
                    "description_ja": "名前",
                    "description_en": "Name",
                    "data_type": "object",
                    "is_nullable": True,
                    "is_primary_key": False,
                    "is_foreign_key": False,
                    "foreign_key_ref": None,
                    "tags": [],
                },
                {
                    "name": "score",
                    "description_ja": "スコア",
                    "description_en": "Score",
                    "data_type": "int64",
                    "is_nullable": True,
                    "is_primary_key": False,
                    "is_foreign_key": False,
                    "foreign_key_ref": None,
                    "tags": [],
                },
            ],
        }
    )
    sql_response = "SELECT name FROM test ORDER BY score DESC LIMIT 1"
    score_response = json.dumps({"correctness": 8, "readability": 8, "issues": []})

    call_count = 0

    async def mock_chat(self_inner, prompt):
        nonlocal call_count
        call_count += 1
        if "メタデータ" in prompt and "スキーマサマリ" in prompt:
            return LLMResponse(content=metadata_json, model="chat")
        elif "SELECT" in prompt.upper() or "SQL" in prompt:
            return LLMResponse(content=sql_response, model="chat")
        else:
            return LLMResponse(content=score_response, model="chat")

    import agent.llm.litellm_client as llm_mod

    monkeypatch.setattr(llm_mod.LiteLLMClient, "chat", mock_chat)

    csv_bytes = make_csv_bytes()
    questions = json.dumps(["スコアが最も高い人は？"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/analyze",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
            data={"questions": questions},
        )

    assert response.status_code == 200
    data = response.json()
    assert "check_results" in data
    assert "catalog_outputs" in data
    assert "textsql_comparison" in data


@pytest.mark.asyncio
async def test_get_root_returns_service_info():
    """HTML フロントエンドは廃止。ルートはサービス情報 JSON を返す。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "catalog-agent"
    assert "process_file" in data["tools"]
    assert data["mcp_endpoint"] == "/mcp"
