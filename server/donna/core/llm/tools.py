"""
Tool utilities for LLM function calling support.
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Union

import litellm

from donna.core.llm.response import ToolCall

logger = logging.getLogger(__name__)


def supports_function_calling(model: str) -> bool:
    """
    Check if a model supports function calling.

    Args:
        model: The model name to check

    Returns:
        True if the model supports function calling, False otherwise
    """
    try:
        return litellm.supports_function_calling(model=model)
    except Exception as e:
        logger.warning(f"Error checking function calling support for {model}: {e}")
        return False


def supports_parallel_function_calling(model: str) -> bool:
    """
    Check if a model supports parallel function calling.

    Args:
        model: The model name to check

    Returns:
        True if the model supports parallel function calling, False otherwise
    """
    try:
        return litellm.supports_parallel_function_calling(model=model)
    except Exception as e:
        logger.warning(
            f"Error checking parallel function calling support for {model}: {e}"
        )
        return False


def function_to_dict(func: Callable) -> Dict[str, Any]:
    """
    Convert a Python function to a dictionary for OpenAI function calling.

    Args:
        func: The function to convert

    Returns:
        Dictionary representation of the function for OpenAI function calling
    """
    try:
        return litellm.utils.function_to_dict(func)
    except Exception as e:
        logger.error(f"Error converting function to dict: {e}")
        raise


def create_tool_from_function(func: Callable) -> Dict[str, Any]:
    """
    Create a tool definition from a Python function.

    Args:
        func: The function to convert to a tool

    Returns:
        Tool definition dictionary
    """
    function_dict = function_to_dict(func)
    return {"type": "function", "function": function_dict}


def create_tools_from_functions(functions: List[Callable]) -> List[Dict[str, Any]]:
    """
    Create tool definitions from a list of Python functions.

    Args:
        functions: List of functions to convert to tools

    Returns:
        List of tool definition dictionaries
    """
    return [create_tool_from_function(func) for func in functions]


def execute_tool_call(
    tool_call: ToolCall, available_functions: Dict[str, Callable]
) -> str:
    """
    Execute a tool call with the provided function.

    Args:
        tool_call: The tool call to execute
        available_functions: Dictionary mapping function names to callable functions

    Returns:
        String result of the function execution
    """
    try:
        function_name = tool_call.function["name"]
        function_args = tool_call.function.get("arguments", "{}")

        if function_name not in available_functions:
            error_msg = f"Function {function_name} not found in available functions"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        # Parse function arguments
        if isinstance(function_args, str):
            try:
                function_args = json.loads(function_args)
            except json.JSONDecodeError as e:
                error_msg = f"Invalid JSON in function arguments: {e}"
                logger.error(error_msg)
                return json.dumps({"error": error_msg})

        # Execute the function
        function_to_call = available_functions[function_name]
        result = function_to_call(**function_args)

        # Convert result to JSON string if it's not already
        if isinstance(result, str):
            return result
        else:
            return json.dumps(result)

    except Exception as e:
        error_msg = f"Error executing tool call: {e}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg})


def create_tool_message(
    tool_call_id: str, content: str, name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a tool message for the conversation.

    Args:
        tool_call_id: The ID of the tool call
        content: The content/result of the tool execution
        name: Optional name of the tool

    Returns:
        Tool message dictionary
    """
    return {
        "role": "tool",
        "content": content,
        "tool_call_id": tool_call_id,
        "name": name,
    }


def process_tool_calls(
    tool_calls: List[ToolCall], available_functions: Dict[str, Callable]
) -> List[Dict[str, Any]]:
    """
    Process multiple tool calls and return tool messages.

    Args:
        tool_calls: List of tool calls to execute
        available_functions: Dictionary mapping function names to callable functions

    Returns:
        List of tool message dictionaries
    """
    tool_messages = []

    for tool_call in tool_calls:
        try:
            # Execute the tool call
            result = execute_tool_call(tool_call, available_functions)

            # Create tool message
            tool_message = create_tool_message(
                tool_call_id=tool_call.id,
                content=result,
                name=tool_call.function.get("name"),
            )
            tool_messages.append(tool_message)

        except Exception as e:
            logger.error(f"Error processing tool call {tool_call.id}: {e}")
            # Create error message
            error_message = create_tool_message(
                tool_call_id=tool_call.id,
                content=json.dumps({"error": str(e)}),
                name=tool_call.function.get("name"),
            )
            tool_messages.append(error_message)

    return tool_messages


def extract_tool_calls_from_response(response: Any) -> List[ToolCall]:
    """
    Extract tool calls from a LiteLLM response.

    Args:
        response: The LiteLLM response object

    Returns:
        List of ToolCall objects
    """
    tool_calls = []

    try:
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tool_call in message.tool_calls:
                    tool_call_obj = ToolCall(
                        id=tool_call.id,
                        type=getattr(tool_call, "type", "function"),
                        function={
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    )
                    tool_calls.append(tool_call_obj)
    except Exception as e:
        logger.error(f"Error extracting tool calls from response: {e}")

    return tool_calls


def validate_tool_choice(
    tool_choice: Union[str, Dict[str, Any]], tools: List[Dict[str, Any]]
) -> Union[str, Dict[str, Any]]:
    """
    Validate and normalize tool_choice parameter.

    Args:
        tool_choice: The tool choice parameter
        tools: List of available tools

    Returns:
        Validated tool choice
    """
    if tool_choice is None:
        return "auto"

    if isinstance(tool_choice, str):
        valid_choices = ["auto", "none"]
        if tool_choice not in valid_choices:
            logger.warning(f"Invalid tool_choice '{tool_choice}', defaulting to 'auto'")
            return "auto"
        return tool_choice

    if isinstance(tool_choice, dict):
        if "type" not in tool_choice or "function" not in tool_choice:
            logger.warning("Invalid tool_choice dict format, defaulting to 'auto'")
            return "auto"

        # Validate that the specified function exists in tools
        function_name = tool_choice.get("function", {}).get("name")
        if function_name:
            tool_names = [tool.get("function", {}).get("name") for tool in tools]
            if function_name not in tool_names:
                logger.warning(
                    f"Function '{function_name}' not found in available tools, defaulting to 'auto'"
                )
                return "auto"

        return tool_choice

    logger.warning(
        f"Invalid tool_choice type {type(tool_choice)}, defaulting to 'auto'"
    )
    return "auto"
