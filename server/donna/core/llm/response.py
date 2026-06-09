from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel


class ToolCall(BaseModel):
    """Represents a tool call from the LLM"""

    id: str
    type: str = "function"
    function: Dict[str, Any]


class ToolMessage(BaseModel):
    """Represents a tool message in the conversation"""

    role: str = "tool"
    content: str
    tool_call_id: str
    name: Optional[str] = None


class LLMResponse(BaseModel):
    """Unified response format for all LLM providers"""

    content: Union[str, BaseModel]
    raw_response: Any = None
    metadata: Optional[Dict[str, Any]] = None
    usage: Optional[Dict[str, int]] = None
    model: Optional[str] = None
    generation_id: Optional[str] = None
    provider: Optional[str] = None
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
