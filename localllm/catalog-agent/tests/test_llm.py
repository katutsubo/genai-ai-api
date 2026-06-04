from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from agent.llm.litellm_client import LiteLLMClient, LLMParseError


def make_mock_response(content: str, status_code: int = 200):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "model": "chat",
    }
    return mock_resp


@pytest.mark.asyncio
async def test_chat_success():
    client = LiteLLMClient()
    mock_resp = make_mock_response('{"result": "ok"}')

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await client.chat("test prompt")
        assert result.content == '{"result": "ok"}'
        assert result.model == "chat"


@pytest.mark.asyncio
async def test_chat_retries_on_parse_error():
    client = LiteLLMClient()

    bad_resp = MagicMock()
    bad_resp.raise_for_status = MagicMock()
    bad_resp.json.side_effect = Exception("parse error")

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return bad_resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.post = mock_post
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(LLMParseError):
            await client.chat("test prompt")

    assert call_count == 3


@pytest.mark.asyncio
async def test_chat_connection_error_retries_then_raises():
    """ConnectError is retried 3 times then raises LLMParseError."""
    client = LiteLLMClient()
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connection refused")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.post = mock_post
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(LLMParseError):
            await client.chat("test prompt")

    assert call_count == 3
