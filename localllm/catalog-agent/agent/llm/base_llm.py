from abc import ABC, abstractmethod

from agent.models import LLMResponse


class BaseLLM(ABC):
    @abstractmethod
    async def chat(self, prompt: str) -> LLMResponse:
        pass
