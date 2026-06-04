from unittest.mock import AsyncMock, MagicMock

import pytest
from agent.models import LLMResponse


@pytest.fixture
def mock_llm_response():
    return LLMResponse(content='{"table_name": "test"}', model="chat")


@pytest.fixture
def mock_llm_client(mock_llm_response):
    client = MagicMock()
    client.chat = AsyncMock(return_value=mock_llm_response)
    return client


@pytest.fixture
def mock_llm_connection_error():
    client = MagicMock()
    client.chat = AsyncMock(side_effect=ConnectionError("LLM not available"))
    return client
