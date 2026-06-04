import pytest
from httpx import ASGITransport, AsyncClient
from main import app


@pytest.mark.asyncio
async def test_outputs_404_when_missing():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/outputs/nonexistent_table/catalog.md")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_outputs_returns_file(tmp_path, monkeypatch):
    import agent.config

    monkeypatch.setattr(agent.config.config, "OUTPUT_DIR", str(tmp_path))

    catalog_dir = tmp_path / "catalog" / "sample"
    catalog_dir.mkdir(parents=True)
    (catalog_dir / "catalog.md").write_text("# catalog")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/outputs/sample/catalog.md")
    assert response.status_code == 200
