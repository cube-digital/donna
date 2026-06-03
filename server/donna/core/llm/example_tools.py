"""
Example usage of the enhanced LLM provider with tool/function calling support.
"""

import json

from donna.core.llm.provider import LLMProvider
from donna.core.llm.tools import create_tool_from_function


def get_current_weather(location: str, unit: str = "fahrenheit") -> str:
    """
    Get the current weather in a given location.

    Args:
        location: The city and state, e.g. San Francisco, CA
        unit: Temperature unit (celsius or fahrenheit)

    Returns:
        JSON string with weather information
    """
    # Mock weather data
    weather_data = {
        "tokyo": {"temperature": "10", "unit": "celsius"},
        "san francisco": {"temperature": "72", "unit": "fahrenheit"},
        "paris": {"temperature": "22", "unit": "celsius"},
    }

    location_lower = location.lower()
    for city, data in weather_data.items():
        if city in location_lower:
            return json.dumps(
                {
                    "location": location,
                    "temperature": data["temperature"],
                    "unit": data["unit"],
                }
            )

    return json.dumps({"location": location, "temperature": "unknown", "unit": unit})


def get_stock_price(symbol: str) -> str:
    """
    Get the current stock price for a given symbol.

    Args:
        symbol: Stock symbol (e.g., AAPL, GOOGL)

    Returns:
        JSON string with stock price information
    """
    # Mock stock data
    stock_data = {
        "AAPL": {"price": 150.25, "change": "+2.15"},
        "GOOGL": {"price": 2800.50, "change": "-15.30"},
        "MSFT": {"price": 350.75, "change": "+5.20"},
    }

    symbol_upper = symbol.upper()
    if symbol_upper in stock_data:
        data = stock_data[symbol_upper]
        return json.dumps(
            {"symbol": symbol_upper, "price": data["price"], "change": data["change"]}
        )

    return json.dumps({"symbol": symbol_upper, "price": "unknown", "change": "unknown"})


def main():
    """Example usage of the enhanced LLM provider with tools."""

    # Initialize the provider
    provider = LLMProvider(
        model="anthropic/claude-opus-4-20250514",
    )

    # Create tools from functions
    weather_tool = create_tool_from_function(get_current_weather)
    stock_tool = create_tool_from_function(get_stock_price)
    tools = [weather_tool, stock_tool]

    # Available functions for execution
    available_functions = {
        "get_current_weather": get_current_weather,
        "get_stock_price": get_stock_price,
    }

    # Example 1: Simple function calling
    print("=== Example 1: Weather Query ===")
    response = provider.get_answer(
        prompt="What's the weather like in Tokyo and San Francisco?",
        tools=tools,
        available_functions=available_functions,
        temperature=0.7,
    )

    print(f"Response: {response.content}")
    if response.tool_calls:
        print(f"Tool calls made: {len(response.tool_calls)}")
        for tool_call in response.tool_calls:
            print(
                f"  - {tool_call.function['name']}: {tool_call.function['arguments']}"
            )

    print("\n" + "=" * 50 + "\n")

    # Example 2: Stock price query
    print("=== Example 2: Stock Price Query ===")
    response = provider.get_answer(
        prompt="What are the current stock prices for AAPL and GOOGL?",
        tools=tools,
        available_functions=available_functions,
        temperature=0.7,
    )

    print(f"Response: {response.content}")
    if response.tool_calls:
        print(f"Tool calls made: {len(response.tool_calls)}")
        for tool_call in response.tool_calls:
            print(
                f"  - {tool_call.function['name']}: {tool_call.function['arguments']}"
            )

    print("\n" + "=" * 50 + "\n")

    # Example 3: Chat with tools
    print("=== Example 3: Chat with Tools ===")
    messages = [
        {
            "role": "user",
            "content": "I need to check the weather in Paris and the stock price of MSFT.",
        }
    ]

    response = provider.chat(
        messages=messages,
        tools=tools,
        available_functions=available_functions,
        temperature=0.7,
    )

    print(f"Response: {response.content}")
    if response.tool_calls:
        print(f"Tool calls made: {len(response.tool_calls)}")
        for tool_call in response.tool_calls:
            print(
                f"  - {tool_call.function['name']}: {tool_call.function['arguments']}"
            )

    print("\n" + "=" * 50 + "\n")

    # Example 4: Tool choice control
    print("=== Example 4: Specific Tool Choice ===")
    response = provider.get_answer(
        prompt="What's the weather like in New York?",
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "get_current_weather"}},
        available_functions=available_functions,
        temperature=0.7,
    )

    print(f"Response: {response.content}")
    if response.tool_calls:
        print(f"Tool calls made: {len(response.tool_calls)}")
        for tool_call in response.tool_calls:
            print(
                f"  - {tool_call.function['name']}: {tool_call.function['arguments']}"
            )


if __name__ == "__main__":
    main()
