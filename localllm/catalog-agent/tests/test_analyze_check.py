import time

import pytest
from httpx import ASGITransport, AsyncClient
from main import app


def make_csv_bytes(content: str = "id,name\n1,Alice\n") -> bytes:
    return content.encode("utf-8")


@pytest.mark.asyncio
async def test_analyze_returns_check_results():
    csv_bytes = make_csv_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/analyze",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
        )
    assert response.status_code == 200
    data = response.json()
    assert "check_results" in data
    assert isinstance(data["check_results"], list)


@pytest.mark.asyncio
async def test_analyze_empty_file_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/analyze",
            files={"file": ("empty.csv", b"", "text/csv")},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_analyze_non_csv_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/analyze",
            files={"file": ("test.txt", b"hello world", "text/plain")},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_analyze_llm_unavailable_still_returns_check_results(monkeypatch):
    from unittest.mock import AsyncMock

    import agent.llm.litellm_client as llm_mod

    monkeypatch.setattr(
        llm_mod.LiteLLMClient, "chat", AsyncMock(side_effect=ConnectionError("LLM down"))
    )

    csv_bytes = make_csv_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/analyze",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
        )
    assert response.status_code == 200
    data = response.json()
    assert "check_results" in data
    assert isinstance(data["check_results"], list)


@pytest.mark.asyncio
async def test_analyze_check_within_30_seconds():
    csv_bytes = make_csv_bytes()
    start = time.time()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/analyze",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
        )
    elapsed = time.time() - start
    assert response.status_code == 200
    assert elapsed < 30, f"Check took {elapsed:.1f}s, expected < 30s"
