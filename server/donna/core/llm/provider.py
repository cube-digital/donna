# Disable LiteLLM logging to prevent warnings
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Type, Union

import litellm
from dotenv import load_dotenv
from litellm import completion
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
)
from pydantic import BaseModel, ValidationError

from donna.core.llm.config import PROVIDER_CONFIGS
from donna.core.llm.interface import LLMInterface
from donna.core.llm.response import LLMResponse
from donna.core.observability.decorators import observe_llm
from donna.core.llm.tools import (
    extract_tool_calls_from_response,
    process_tool_calls,
    supports_function_calling,
    validate_tool_choice,
)

# Completely disable LiteLLM logging and callbacks
litellm_logger = logging.getLogger("litellm")
litellm_logger.setLevel(logging.ERROR)

# Disable all callbacks and logging
litellm.callbacks = []
litellm.success_callback = []
litellm.failure_callback = []

# Disable logging callbacks
litellm.logging_config = None

# Set environment variable to disable logging
os.environ["LITELLM_DISABLE_LOGGING"] = "true"


class Message:
    """Helper class for message formatting"""

    @staticmethod
    def system(content: str) -> Dict[str, str]:
        return {"role": "system", "content": content}

    @staticmethod
    def user(content: str) -> Dict[str, str]:
        return {"role": "user", "content": content}

    @staticmethod
    def assistant(content: str) -> Dict[str, str]:
        return {"role": "assistant", "content": content}


def _detect_provider(model: str) -> str:
    m = model.lower()
    if m.startswith("gpt-") or m.startswith("openai/"):
        return "openai"
    elif m.startswith("claude-") or m.startswith("anthropic/"):
        return "anthropic"
    elif m.startswith("gemini-") or m.startswith("google/"):
        return "google"
    elif m.startswith("mistral-") or m.startswith("mistral/"):
        return "mistral"
    else:
        return "openai"  # Default to OpenAI


def _model_accepts_temperature(model: str) -> bool:
    """Whether ``model`` accepts the ``temperature`` completion parameter.

    Anthropic's Claude 4.x reasoning models (Opus 4.x, …) have deprecated
    ``temperature`` — passing it returns ``invalid_request_error: temperature
    is deprecated for this model``. OpenAI's o-series reasoning models behave
    the same way. We strip the param for those families and pass it through
    for everything else.
    """
    m = model.lower()
    # Anthropic Claude 4.x and beyond — reasoning-class models.
    if "claude-opus-4" in m or "claude-sonnet-4" in m or "claude-haiku-4" in m:
        return False
    # OpenAI reasoning models (o1, o3, …).
    if m.startswith("o1") or m.startswith("o3") or "/o1-" in m or "/o3-" in m:
        return False
    return True


def _extract_json_from_markdown(content: str) -> Optional[Any]:
    """
    Extract JSON from markdown code blocks.

    Args:
        content: String that may contain JSON wrapped in markdown code blocks

    Returns:
        Parsed JSON object if found, None otherwise
    """
    import re

    # Pattern 1: Standard markdown with closing backticks
    # Handles: ```json\n{...}\n``` or ```\n{...}\n```
    json_pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
    match = re.search(json_pattern, content, re.DOTALL)

    if match:
        json_str = match.group(1).strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # Pattern 2: Markdown without closing backticks (truncated response)
    # Extract everything after ```json until end of string
    truncated_pattern = r"```(?:json)?\s*\n?(\{.*)"
    truncated_match = re.search(truncated_pattern, content, re.DOTALL)

    if truncated_match:
        json_str = truncated_match.group(1).strip()
        # Remove trailing ``` if present
        json_str = re.sub(r"```\s*$", "", json_str).strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # Try to repair truncated JSON by adding missing brackets
            repaired = _repair_truncated_json(json_str)
            if repaired:
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

    # Pattern 3: Raw JSON without markdown (starts with {)
    if content.strip().startswith("{"):
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            repaired = _repair_truncated_json(content.strip())
            if repaired:
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

    return None


def _repair_truncated_json(json_str: str) -> Optional[str]:
    """
    Attempt to repair truncated JSON by adding missing closing brackets.
    Only repairs simple cases where the structure is clear.
    """
    if not json_str:
        return None

    # Count opening vs closing brackets
    open_braces = json_str.count("{")
    close_braces = json_str.count("}")
    open_brackets = json_str.count("[")
    close_brackets = json_str.count("]")

    # If already balanced, return as-is
    if open_braces == close_braces and open_brackets == close_brackets:
        return json_str

    # Remove trailing incomplete elements (partial strings, commas)
    # Find the last complete value
    repaired = json_str.rstrip()

    # Remove trailing partial content after last complete bracket/brace
    while repaired and repaired[-1] in ',: \t\n\r"':
        repaired = repaired[:-1].rstrip()

    # Add missing closing brackets/braces
    missing_brackets = close_brackets - open_brackets
    missing_braces = close_braces - open_braces

    # Add missing ] then }
    if missing_brackets < 0:
        repaired += "]" * abs(missing_brackets)
    if missing_braces < 0:
        repaired += "}" * abs(missing_braces)

    return repaired


def _resolve_ref(ref: str, root: dict) -> dict:
    """Resolve a JSON-schema ``$ref`` like ``#/$defs/PMDoc`` inside ``root``."""
    if not ref.startswith("#/"):
        return {}
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        if not isinstance(node, dict):
            return {}
        node = node.get(part, {})
    return node if isinstance(node, dict) else {}


def _example_for_field(
    field_info: dict, root: dict, field_name: str = "", _depth: int = 0
) -> Any:
    """Produce a representative example value for a JSON-schema field node.

    Recurses into nested ``$ref``/``object``/``array`` schemas so the LLM sees
    a properly nested example instead of a placeholder string — that
    placeholder pattern is what made Anthropic's Claude 4.x family
    stringify ``PMDoc`` as a quoted JSON blob and stuff plain strings into
    arrays of Pydantic models.
    """
    if _depth > 4:
        return "..."

    # Direct ``$ref`` to a definition (typical for nested Pydantic models).
    ref = field_info.get("$ref")
    if ref:
        target = _resolve_ref(ref, root)
        return _example_for_field(target, root, field_name, _depth + 1)

    # ``anyOf`` (e.g. ``Optional[Model]`` / unions). Pick the first non-null.
    for variant in field_info.get("anyOf", []) or []:
        if variant.get("type") != "null":
            return _example_for_field(variant, root, field_name, _depth + 1)

    field_type = field_info.get("type")

    if field_type == "object" or (field_type is None and "properties" in field_info):
        nested = {}
        for sub_name, sub_info in (field_info.get("properties") or {}).items():
            nested[sub_name] = _example_for_field(
                sub_info, root, sub_name, _depth + 1
            )
        return nested

    if field_type == "array":
        items = field_info.get("items") or {}
        item_example = _example_for_field(items, root, field_name, _depth + 1)
        return [item_example]

    if field_type == "string":
        lower = field_name.lower()
        if "content" in lower or "text" in lower:
            return "Your actual content here as a string..."
        if "summary" in lower:
            return "Brief summary of the content"
        return f"<{field_name} value>"

    if field_type in ("integer", "number"):
        return 0
    if field_type == "boolean":
        return True

    return f"<{field_name}>"


def _summarise_field_type(field_info: dict, root: dict, _depth: int = 0) -> str:
    """Human-readable type label that distinguishes nested models from primitives."""
    if _depth > 4:
        return "..."

    ref = field_info.get("$ref")
    if ref:
        # Show the model name from the $ref so the LLM knows it's a nested object.
        return ref.rsplit("/", 1)[-1]

    for variant in field_info.get("anyOf", []) or []:
        if variant.get("type") != "null":
            return _summarise_field_type(variant, root, _depth + 1)

    field_type = field_info.get("type")
    if field_type == "array":
        items = field_info.get("items") or {}
        return f"array<{_summarise_field_type(items, root, _depth + 1)}>"
    if field_type == "object" or (field_type is None and "properties" in field_info):
        return "object"
    return field_type or "string"


def _build_schema_instruction(model_cls: Type[BaseModel]) -> str:
    """
    Build a clear schema instruction with example for LLM.

    Instead of showing the raw JSON schema (which LLMs often misinterpret),
    we show a simplified field list and a concrete example — including the
    full nested structure for fields whose type is itself a Pydantic model
    or a list of Pydantic models.
    """
    schema = model_cls.model_json_schema()
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    field_lines: list[str] = []
    example_obj: dict[str, Any] = {}

    for field_name, field_info in properties.items():
        type_label = _summarise_field_type(field_info, schema)
        description = field_info.get("description", "")
        is_required = field_name in required

        req_marker = " (REQUIRED)" if is_required else " (optional)"
        field_lines.append(f"  - {field_name}: {type_label}{req_marker}")
        if description:
            field_lines.append(f"      Description: {description}")

        example_obj[field_name] = _example_for_field(field_info, schema, field_name)

    fields_str = "\n".join(field_lines)
    example_str = json.dumps(example_obj, indent=2, ensure_ascii=False)

    return f"""FIELDS:
{fields_str}

EXAMPLE OUTPUT STRUCTURE:
{example_str}

IMPORTANT: Replace the example values with your actual generated content.
Nested objects in the example show the REQUIRED shape — keep them as JSON
objects, NOT as strings."""


def _fix_json_string_fields(data: dict, model_cls: Type[BaseModel]) -> dict:
    """
    Fix cases where LLM returns nested model fields as JSON strings instead of objects.

    For example, if LLM returns:
    {"document_metadata": '{"id": "doc-1", "title": "..."}', "sections": ["plain string", ...]}

    We parse the JSON strings into proper dicts/objects so Pydantic can validate them.
    """
    if not isinstance(data, dict):
        return data

    import typing
    import types

    fixed_data = dict(data)

    for field_name, field_info in model_cls.model_fields.items():
        if field_name not in fixed_data:
            continue

        value = fixed_data[field_name]
        annotation = field_info.annotation

        # Unwrap Optional[X] -> X
        origin = getattr(annotation, "__origin__", None)
        if origin is Union or (hasattr(types, "UnionType") and isinstance(annotation, types.UnionType)):
            args = [a for a in annotation.__args__ if a is not type(None)]
            if len(args) == 1:
                annotation = args[0]
                origin = getattr(annotation, "__origin__", None)

        # Case 1: Field expects a BaseModel subclass but got a JSON string
        if isinstance(value, str) and isinstance(annotation, type) and issubclass(annotation, BaseModel):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    fixed_data[field_name] = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        # Case 2: Field expects List[SomeModel] but got List[str] with JSON strings
        elif isinstance(value, list) and origin is list:
            args = getattr(annotation, "__args__", ())
            if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                item_cls = args[0]
                fixed_items = []
                for item in value:
                    if isinstance(item, str):
                        try:
                            parsed = json.loads(item)
                            if isinstance(parsed, dict):
                                fixed_items.append(parsed)
                            else:
                                fixed_items.append(item)
                        except (json.JSONDecodeError, TypeError):
                            # Plain string that's not JSON - skip or wrap
                            fixed_items.append(item)
                    else:
                        fixed_items.append(item)
                fixed_data[field_name] = fixed_items

    return fixed_data


def _fix_nested_schema_values(data: dict, model_cls: Type[BaseModel]) -> dict:
    """
    Fix cases where LLM returns schema-like nested objects instead of values,
    or nested model fields as JSON strings.

    For example, if LLM returns:
    {"content": {"description": "actual text...", "type": "string"}}

    We try to extract the actual value:
    {"content": "actual text..."}
    """
    if not isinstance(data, dict):
        return data

    # First, fix JSON string fields (e.g. nested models returned as strings)
    data = _fix_json_string_fields(data, model_cls)

    schema = model_cls.model_json_schema()
    properties = schema.get("properties", {})
    fixed_data = {}

    for field_name, field_value in data.items():
        if field_name not in properties:
            fixed_data[field_name] = field_value
            continue

        expected_type = properties[field_name].get("type", "string")

        # Check if the value looks like a schema object instead of actual data
        if isinstance(field_value, dict) and expected_type == "string":
            # LLM returned {"description": "...", "type": "string"} instead of a string
            if "description" in field_value and "type" in field_value:
                # Extract the description as the actual value
                actual_value = field_value.get("description", "")
                logging.info(f"Fixed nested schema for field '{field_name}'")
                fixed_data[field_name] = actual_value
            elif "value" in field_value:
                # Sometimes LLM returns {"value": "actual content"}
                fixed_data[field_name] = field_value.get("value", "")
            elif len(field_value) == 1:
                # Single key dict - extract the value
                fixed_data[field_name] = list(field_value.values())[0]
            else:
                # Unknown structure - try to convert to string
                fixed_data[field_name] = json.dumps(field_value, ensure_ascii=False)
        elif isinstance(field_value, dict) and expected_type == "array":
            # LLM returned dict instead of array
            if "items" in field_value:
                fixed_data[field_name] = field_value.get("items", [])
            else:
                fixed_data[field_name] = list(field_value.values())
        else:
            fixed_data[field_name] = field_value

    return fixed_data


def _pydantic_validate(model_cls: Type[BaseModel], data: Any) -> BaseModel:
    """Validate data against a Pydantic model with proper error handling."""
    try:
        if isinstance(data, dict):
            # Try direct validation first
            try:
                return model_cls(**data)
            except ValidationError:
                # Try fixing nested schema values
                fixed_data = _fix_nested_schema_values(data, model_cls)
                return model_cls(**fixed_data)

        elif isinstance(data, str):
            # First try to extract JSON from markdown code blocks
            extracted_json = _extract_json_from_markdown(data)
            if extracted_json is not None:
                try:
                    return model_cls(**extracted_json)
                except ValidationError:
                    # Try fixing nested schema values
                    fixed_data = _fix_nested_schema_values(extracted_json, model_cls)
                    try:
                        return model_cls(**fixed_data)
                    except ValidationError as e:
                        logging.warning(
                            f"Pydantic validation failed for extracted JSON: {e}"
                        )
                    # Fall through to try direct JSON parsing

            # Try to parse as direct JSON string
            try:
                json_data = json.loads(data)
                try:
                    return model_cls(**json_data)
                except ValidationError:
                    # Try fixing nested schema values
                    fixed_data = _fix_nested_schema_values(json_data, model_cls)
                    return model_cls(**fixed_data)
            except json.JSONDecodeError:
                # Only log warning if we couldn't extract from markdown either
                if extracted_json is None:
                    logging.warning(f"Invalid JSON string: {data[:200]}...")
                # Return raw content if JSON parsing fails
                return data
        else:
            logging.warning(f"Expected dict or JSON string, got {type(data)}")
            # Return raw content if type is unexpected
            return data
    except ValidationError as e:
        logging.warning(f"Pydantic validation failed: {e}")
        # Return raw content if validation fails
        return data
    except Exception as e:
        logging.error(f"Unexpected error during Pydantic validation: {e}")
        # Return raw content for any other errors
        return data


class LLMProvider(LLMInterface):
    """Unified LLM provider class"""

    RETRYABLE_EXCEPTIONS = (
        RateLimitError,
        APIConnectionError,
        ServiceUnavailableError,
        InternalServerError,
        APIError,
    )

    def __init__(
        self,
        model: str,
        default_system_prompt: Optional[Dict[str, str]] = None,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        callbacks: Optional[List[str]] = None,
        fallbacks: Optional[List[str]] = None,
        default_language: str = "en",
        disable_litellm_callbacks: bool = True,
        max_retries: int = 5,
        retry_min_wait: float = 15.0,
        retry_max_wait: float = 200.0,
        **provider_kwargs,
    ):
        super().__init__(model)
        self.default_system_prompt = default_system_prompt or {}
        self.api_key = api_key
        self.api_base = api_base
        self.callbacks = callbacks or []
        self.fallbacks = fallbacks or []
        self.default_language = default_language
        self.provider_kwargs = provider_kwargs
        self.last_generation_id = None

        self.max_retries = max_retries
        self.retry_min_wait = retry_min_wait
        self.retry_max_wait = retry_max_wait

        self.provider = _detect_provider(model)
        self.provider_config = PROVIDER_CONFIGS.get(self.provider, {})

        self._setup_callbacks(disable_litellm_callbacks)

    def _setup_callbacks(self, disable: bool) -> None:
        # Quiet noisy logging warnings by disabling callbacks.
        # You can set disable=False if you explicitly want LiteLLM callbacks.
        if disable:
            litellm.callbacks = []
            litellm.success_callback = []
            litellm.failure_callback = []
        else:
            litellm.callbacks = self.callbacks or []

    @staticmethod
    def _format_prompt(prompt: str, **kwargs) -> str:
        try:
            return prompt.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"Missing required parameter: {e}")

    def _make_completion_call(self, completion_params: dict):
        """
        Make a completion call with exponential backoff retry on rate limits.

        Args:
            completion_params: Parameters for litellm.completion

        Returns:
            The completion response
        """
        attempt = 0
        last_exception = None

        while attempt < self.max_retries:
            try:
                return completion(**completion_params)

            except self.RETRYABLE_EXCEPTIONS as e:
                attempt += 1
                last_exception = e

                if attempt >= self.max_retries:
                    logging.error(
                        f"Max retries ({self.max_retries}) exceeded. Last error: {e}"
                    )
                    raise

                wait_time = min(
                    self.retry_max_wait, self.retry_min_wait * (2 ** (attempt - 1))
                )

                retry_after = getattr(e, "retry_after", None)
                if retry_after:
                    wait_time = max(wait_time, float(retry_after))

                logging.warning(
                    f"Rate limited on {self.model}. "
                    f"Waiting {wait_time:.1f}s before retry {attempt}/{self.max_retries}. "
                    f"Error: {type(e).__name__}"
                )

                time.sleep(wait_time)

            except Exception:
                # Non-retryable exception, raise immediately
                raise

        if last_exception:
            raise last_exception

    @observe_llm()
    def get_answer(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        formatted_instructions: Optional[Type[BaseModel]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        available_functions: Optional[Dict[str, Callable]] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Get an answer from the LLM provider.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response
            formatted_instructions: Optional Pydantic model for structured output
            tools: Optional list of tool definitions for function calling
            tool_choice: Optional tool choice parameter ("auto", "none", or specific tool)
            available_functions: Optional dict mapping function names to callable functions
            **kwargs: Additional provider-specific arguments

        Returns:
            LLMResponse object
        """
        try:
            # Check if the prompt contains actual placeholders (single braces) vs examples (double braces)
            import re

            # Find all single brace placeholders (actual parameters to format)
            single_braces = re.findall(r"\{(\w+)\}", prompt)

            if single_braces:
                # Has actual placeholders, try to format
                try:
                    formatted_prompt = self._format_prompt(prompt, **kwargs)
                except (KeyError, ValueError, IndexError):
                    # If formatting fails, use the prompt as-is (already formatted)
                    formatted_prompt = prompt
            else:
                # No single brace placeholders, use as-is (already formatted)
                formatted_prompt = prompt

            # Prepare messages
            messages = []
            if system_prompt:
                messages.append(Message.system(system_prompt))
            messages.append(Message.user(formatted_prompt))

            # Get provider-specific configuration
            provider_config = self.provider_config.copy()
            provider_config.update(self.provider_kwargs)

            # Prepare completion parameters
            completion_params = {
                "model": self.model,
                "messages": messages,
                "stream": stream,
            }
            if _model_accepts_temperature(self.model):
                completion_params["temperature"] = temperature

            if max_tokens:
                completion_params["max_tokens"] = max_tokens

            # Handle tools if provided
            if tools:
                # Check if model supports function calling
                if not supports_function_calling(self.model):
                    logging.warning(
                        f"Model {self.model} does not support function calling, ignoring tools"
                    )
                else:
                    completion_params["tools"] = tools
                    completion_params["tool_choice"] = validate_tool_choice(
                        tool_choice, tools
                    )

            # Handle structured output BEFORE making the call
            if formatted_instructions and not stream:
                # For models that support response_format
                if self._supports_json_mode():
                    completion_params["response_format"] = {"type": "json_object"}

                # Build a clear schema representation and example
                schema_info = _build_schema_instruction(formatted_instructions)

                # Append JSON instruction to system prompt
                json_instruction = (
                    f"\n\nCRITICAL: You MUST respond with ONLY valid JSON.\n\n"
                    f"EXPECTED FORMAT:\n{schema_info}\n\n"
                    "RULES:\n"
                    "1. Output ONLY the raw JSON object - no markdown, no code blocks, no ```\n"
                    "2. Each field value must be the actual data, NOT a schema description\n"
                    "3. String fields should contain the actual text content\n"
                    "4. Do NOT include 'type' or 'description' keys - just the field values\n"
                    "5. Ensure all required fields are present"
                )
                if messages and messages[0].get("role") == "system":
                    messages[0]["content"] = messages[0]["content"] + json_instruction
                elif system_prompt:
                    # Update the first message if it's a system message
                    messages[0] = Message.system(system_prompt + json_instruction)
                else:
                    messages.insert(0, Message.system(json_instruction))

            # Add provider-specific parameters
            completion_params.update(provider_config)

            # Add API key if provided
            if self.api_key:
                completion_params["api_key"] = self.api_key

            if self.api_base:
                completion_params["api_base"] = self.api_base

            response = self._make_completion_call(completion_params)

            # Extract response content and tool calls
            if stream:
                # Handle streaming response
                content = ""
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        content += chunk.choices[0].delta.content
                tool_calls = []  # Tool calls not supported in streaming mode
            else:
                # Handle non-streaming response
                content = response.choices[0].message.content
                tool_calls = extract_tool_calls_from_response(response)

            # Handle tool calls if present and functions are available
            if not stream and tool_calls and available_functions:
                try:
                    # Process tool calls and execute functions
                    tool_messages = process_tool_calls(tool_calls, available_functions)

                    # Add the assistant's message with tool calls to conversation
                    assistant_message = {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": [
                            {"id": tc.id, "type": tc.type, "function": tc.function}
                            for tc in tool_calls
                        ],
                    }
                    messages.append(assistant_message)

                    # Add tool messages to conversation for follow-up
                    messages.extend(tool_messages)

                    # Make a follow-up call to get the final response
                    follow_up_params = completion_params.copy()
                    follow_up_params["messages"] = messages
                    # Keep tools but set tool_choice to "none" for final response
                    follow_up_params["tool_choice"] = "none"

                    follow_up_response = completion(**follow_up_params)
                    content = follow_up_response.choices[0].message.content

                    # Update response object for final response
                    response = follow_up_response

                except Exception as e:
                    logging.error(f"Error processing tool calls: {e}")
                    # Continue with original response if tool processing fails

            # Validate structured output if requested (JSON mode was set before the call)
            if formatted_instructions and not stream:
                try:
                    content = _pydantic_validate(formatted_instructions, content)
                except ValidationError as e:
                    logging.warning(f"Failed to validate structured output: {e}")
                    # Return the raw content if validation fails
                    pass

            # Create response object
            llm_response = LLMResponse(
                content=content or "",
                model=self.model,
                provider=self.provider,
                usage={
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(
                        response.usage, "completion_tokens", 0
                    ),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                }
                if response.usage
                else None,
                finish_reason=response.choices[0].finish_reason,
                tool_calls=tool_calls,
            )

            # Store generation ID for tracking
            self.last_generation_id = getattr(response, "id", None)

            return llm_response

        except Exception as e:
            # Log the error
            logging.error(f"LLM call failed: {str(e)}")

            # If we have fallbacks, try them
            if self.fallbacks:
                for fallback_model in self.fallbacks:
                    try:
                        logging.info(f"Trying fallback model: {fallback_model}")
                        fallback_provider = LLMProvider(
                            model=fallback_model,
                            api_key=self.api_key,
                            api_base=self.api_base,
                            **self.provider_kwargs,
                        )
                        return fallback_provider.get_answer(
                            prompt=prompt,
                            system_prompt=system_prompt,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            stream=stream,
                            formatted_instructions=formatted_instructions,
                            tools=tools,
                            tool_choice=tool_choice,
                            available_functions=available_functions,
                            **kwargs,
                        )
                    except Exception as fallback_error:
                        logging.error(
                            f"Fallback model {fallback_model} failed: {fallback_error}"
                        )
                        continue

            # If all fallbacks fail, raise the original error
            raise

    def _supports_json_mode(self) -> bool:
        """Check if the model supports JSON response format."""
        json_mode_models = [
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-4-1106",
            "gpt-3.5-turbo-1106",
            "gemini-1.5",
            "gemini-2",
            "gemini-3",  # Gemini 1.5+ supports it
            "claude-3",  # Claude 3+ supports it via tool use
        ]
        model_lower = self.model.lower()
        return any(m in model_lower for m in json_mode_models)

    def get_structured_answer(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> BaseModel:
        """
        Get a structured answer from the LLM provider.

        Args:
            prompt: The user prompt
            response_model: Pydantic model for the expected response structure
            system_prompt: Optional system prompt
            temperature: Sampling temperature (lower for structured output)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional arguments

        Returns:
            Structured response as Pydantic model
        """
        response = self.get_answer(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            formatted_instructions=response_model,
            max_tokens=max_tokens,
            **kwargs,
        )
        return response.content

    @observe_llm()
    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        stream: bool = False,
        formatted_instructions: Optional[Type[BaseModel]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        available_functions: Optional[Dict[str, Callable]] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Chat using LiteLLM with message history.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            stream: Whether to stream the response
            formatted_instructions: Optional Pydantic model for structured output
            tools: Optional list of tool definitions for function calling
            tool_choice: Optional tool choice parameter ("auto", "none", or specific tool)
            available_functions: Optional dict mapping function names to callable functions
            **kwargs: Additional arguments

        Returns:
            LLMResponse object
        """
        try:
            # Prepend system prompt if provided
            if system_prompt:
                if not messages or messages[0].get("role") != "system":
                    messages = [Message.system(system_prompt), *messages]
                else:
                    messages[0]["content"] = system_prompt

            # Get provider-specific configuration
            provider_config = self.provider_config.copy()
            provider_config.update(self.provider_kwargs)

            # Prepare completion parameters
            completion_params = {
                "model": self.model,
                "messages": messages,
                "stream": stream,
            }
            if _model_accepts_temperature(self.model):
                completion_params["temperature"] = temperature

            # Handle tools if provided
            if tools:
                # Check if model supports function calling
                if not supports_function_calling(self.model):
                    logging.warning(
                        f"Model {self.model} does not support function calling, ignoring tools"
                    )
                else:
                    completion_params["tools"] = tools
                    completion_params["tool_choice"] = validate_tool_choice(
                        tool_choice, tools
                    )

            # Add provider-specific parameters
            completion_params.update(provider_config)

            # Add API key if provided
            if self.api_key:
                completion_params["api_key"] = self.api_key

            if self.api_base:
                completion_params["api_base"] = self.api_base

            # Make the completion call
            response = completion(**completion_params)

            # Extract response content and tool calls
            if stream:
                # Handle streaming response
                content = ""
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        content += chunk.choices[0].delta.content
                tool_calls = []  # Tool calls not supported in streaming mode
            else:
                # Handle non-streaming response
                content = response.choices[0].message.content
                tool_calls = extract_tool_calls_from_response(response)

            # Handle tool calls if present and functions are available
            if not stream and tool_calls and available_functions:
                try:
                    # Process tool calls and execute functions
                    tool_messages = process_tool_calls(tool_calls, available_functions)

                    # Add the assistant's message with tool calls to conversation
                    assistant_message = {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": [
                            {"id": tc.id, "type": tc.type, "function": tc.function}
                            for tc in tool_calls
                        ],
                    }
                    messages.append(assistant_message)

                    # Add tool messages to conversation for follow-up
                    messages.extend(tool_messages)

                    # Make a follow-up call to get the final response
                    follow_up_params = completion_params.copy()
                    follow_up_params["messages"] = messages
                    # Keep tools but set tool_choice to "none" for final response
                    follow_up_params["tool_choice"] = "none"

                    follow_up_response = completion(**follow_up_params)
                    content = follow_up_response.choices[0].message.content

                    # Update response object for final response
                    response = follow_up_response

                except Exception as e:
                    logging.error(f"Error processing tool calls: {e}")
                    # Continue with original response if tool processing fails

            # Validate structured output if requested
            if formatted_instructions:
                try:
                    content = _pydantic_validate(formatted_instructions, content)
                except ValidationError as e:
                    logging.warning(f"Failed to validate structured output: {e}")
                    # Return the raw content if validation fails
                    pass

            # Create response object
            llm_response = LLMResponse(
                content=content or "",
                model=self.model,
                provider=self.provider,
                usage={
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(
                        response.usage, "completion_tokens", 0
                    ),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                }
                if response.usage
                else None,
                finish_reason=response.choices[0].finish_reason,
                tool_calls=tool_calls,
            )

            # Store generation ID for tracking
            self.last_generation_id = getattr(response, "id", None)

            return llm_response

        except Exception as e:
            logging.error(f"Chat call failed: {str(e)}")
            raise


if __name__ == "__main__":
    load_dotenv()

    provider = LLMProvider(
        model="gpt-4o",
        default_system_prompt={"en": "You are a helpful assistant."},
    )

    response = provider.get_answer("What is Python?")
    print(response)
