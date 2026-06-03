from abc import ABC, abstractmethod
from typing import List

from donna.core.llm.factory import LLMFactory
from donna.core.llm.provider import LLMProvider, Message


class BaseChatHandler(ABC):
    def __init__(self, model: str, fallbacks: List[str], **kwargs):
        self.model = model
        self.fallbacks = fallbacks
        self.kwargs = kwargs
        self.llm_factory = LLMFactory()
        self.message = Message()

    @abstractmethod
    def generate_response(self, *args, **kwargs):
        pass

    @abstractmethod
    def get_or_create_deal(self, *args, **kwargs):
        pass

    @property
    def provider(self) -> LLMProvider:
        return LLMFactory.create_with_fallbacks(
            self.model, self.fallbacks, **self.kwargs
        )
