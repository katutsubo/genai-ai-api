import base64
import json

import pytest
from httpx import ASGITransport, AsyncClient
from main import app


def _csv_b64(content: str = "id,name\n1,Alice\n") -> str:
    return base64.b64encode(content.encode("utf-8")).decode("ascii")


async def _post_mcp(client, payload):
    return await client.post("/mcp", json=payload)


@pytest.mark.asyncio
async def test_mcp_initialize():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await _post_mcp(
            client,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert "result" in data
    assert "protocolVersion" in data["result"]
    assert data["result"]["serverInfo"]["name"]


@pytest.mark.asyncio
async def test_mcp_tools_list_contains_analyze_csv():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await _post_mcp(
            client,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
    assert resp.status_code == 200
    tools = resp.json()["result"]["tools"]
    names = [t["name"] for t in tools]
    assert "analyze_csv" in names


@pytest.mark.asyncio
async def test_mcp_initialized_notification_returns_202():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await _post_mcp(
            client,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_mcp_call_analyze_csv_returns_check_results():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await _post_mcp(
            client,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "analyze_csv",
                    "arguments": {"filename": "test.csv", "content_base64": _csv_b64()},
                },
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data
    content = data["result"]["content"]
    assert content[0]["type"] == "text"
    inner = json.loads(content[0]["text"])
    assert "check_results" in inner
    assert isinstance(inner["check_results"], list)


@pytest.mark.asyncio
async def test_mcp_call_analyze_csv_rejects_non_csv():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await _post_mcp(
            client,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "analyze_csv",
                    "arguments": {"filename": "test.txt", "content_base64": _csv_b64()},
                },
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_mcp_call_unknown_tool():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await _post_mcp(
            client,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "nope", "arguments": {}},
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_mcp_unknown_method():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await _post_mcp(
            client,
            {"jsonrpc": "2.0", "id": 6, "method": "does/not/exist", "params": {}},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == -32601
