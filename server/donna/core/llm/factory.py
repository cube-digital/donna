from typing import List

from donna.core.llm.provider import LLMProvider


class LLMFactory:
    """Factory for creating LLM instances"""

    @staticmethod
    def create(model: str, **kwargs) -> LLMProvider:
        """Create a UnifiedLLM instance"""
        return LLMProvider(model=model, **kwargs)

    @staticmethod
    def create_with_fallbacks(
        primary_model: str, fallback_models: List[str], **kwargs
    ) -> LLMProvider:
        """Create a UnifiedLLM with fallback models"""
        return LLMProvider(model=primary_model, fallbacks=fallback_models, **kwargs)
