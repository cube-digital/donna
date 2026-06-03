import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel

from donna.core.llm.response import LLMResponse


class LLMInterface(ABC):
    def __init__(self, model: str):
        self.model = model
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def get_answer(
        self,
        prompt: str,
        temperature: float = 0.7,
        stream: bool = False,
        formatted_instructions: Optional[BaseModel] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        available_functions: Optional[Dict[str, Callable]] = None,
        **kwargs,
    ) -> Union[LLMResponse, Any]:
        pass

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        stream: bool = False,
        formatted_instructions: Optional[BaseModel] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        available_functions: Optional[Dict[str, Callable]] = None,
        **kwargs,
    ) -> Union[LLMResponse, Any]:
        pass
