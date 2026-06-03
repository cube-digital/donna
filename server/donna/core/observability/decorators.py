"""
Stub decorators for the dormant observability stack.

``observe_llm`` is imported by ``donna.core.llm.provider`` but the
real tracing layer is not yet in this codebase. The stub accepts both
``@observe_llm`` and ``@observe_llm(...)`` call shapes so existing
callers don't need to change once a real implementation lands.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable


def observe_llm(*dargs: Any, **dkwargs: Any) -> Any:
    """No-op decorator. Supports both bare ``@observe_llm`` and
    parameterised ``@observe_llm(...)`` usage.
    """

    # @observe_llm (no parens) — dargs[0] is the function.
    if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
        fn: Callable[..., Any] = dargs[0]

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        return wrapper

    # @observe_llm(...) — return the real decorator factory.
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        return wrapper

    return decorator
