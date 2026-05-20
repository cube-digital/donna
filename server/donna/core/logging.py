"""
Structured logging configuration for Donna.

This module provides structured logging using structlog with optional
BetterStack Logtail integration. It includes request context propagation
via Django middleware.

Usage:
    from donna.core.logging import get_logger, update_request_context

    logger = get_logger(__name__)
    logger.info("user_action", user_id="123", action="login")
"""

import logging
import os
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from django.conf import settings


# Request context stored in contextvars for async safety
request_context: ContextVar[dict[str, Any]] = ContextVar("request_context", default={})


def set_request_context(
    request_id: str | None = None,
    user_id: str | None = None,
    company_id: str | None = None,
    operation: str | None = None,
    **kwargs,
) -> str:
    """
    Set the request context that will be included in all logs.

    Args:
        request_id: Unique request identifier
        user_id: User ID from authentication
        company_id: Company/tenant ID
        operation: Operation type or endpoint path
        **kwargs: Additional context fields

    Returns:
        The request_id (generated if not provided)
    """
    if request_id is None:
        request_id = str(uuid.uuid4())

    context = {
        "request_id": request_id,
        "user_id": user_id,
        "company_id": company_id,
        "operation": operation,
        **kwargs,
    }

    # Remove None values to keep logs clean
    context = {k: v for k, v in context.items() if v is not None}
    request_context.set(context)
    return request_id


def update_request_context(**kwargs) -> None:
    """
    Update the current request context with additional fields.

    Args:
        **kwargs: Additional context fields to merge into existing context

    Example:
        update_request_context(user_id="123", user_email="user@example.com")
    """
    current_context = request_context.get({})
    new_fields = {k: v for k, v in kwargs.items() if v is not None}
    current_context.update(new_fields)
    request_context.set(current_context)


def clear_request_context() -> None:
    """Clear the current request context."""
    request_context.set({})


def get_request_context() -> dict[str, Any]:
    """Get the current request context."""
    return request_context.get({})


class NarrioContextProcessor:
    """Custom processor to inject Narrio-specific context into all log records."""

    def __call__(
        self, logger: logging.Logger, method_name: str, event_dict: dict
    ) -> dict:
        # Get current context from contextvars
        context = request_context.get({})
        event_dict.update(context)

        # Add standard fields
        event_dict.setdefault("service", "donna-api")
        event_dict.setdefault("version", os.getenv("APP_VERSION", "1.0.0"))
        event_dict.setdefault(
            "environment", "development" if settings.DEBUG else "production"
        )

        return event_dict


def configure_logging(
    log_level: str = "INFO",
    log_format: str = "json",
) -> None:
    """
    Configure structured logging for the Narrio application.

    Call this at the end of settings.py to initialize logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_format: Output format ("json" for production, "console" for dev)
        enable_logtail: Whether to enable Logtail. Auto-detects if None.
    """
    processors: list = [
        NarrioContextProcessor(),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "console":
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        processors.extend(
            [
                structlog.processors.EventRenamer("message"),
                structlog.processors.JSONRenderer(),
            ]
        )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        context_class=dict,
        cache_logger_on_first_use=True,
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Stdout handler (for CloudWatch/FluentBit/local dev)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(getattr(logging, log_level.upper()))
    root_logger.addHandler(stdout_handler)

    # Logtail handler (optional)
    logtail_token = getattr(settings, "LOGTAIL_SOURCE_TOKEN", "")
    logtail_host = getattr(
        settings, "LOGTAIL_INGESTION_HOST", "in.logs.betterstack.com"
    )


    # Suppress noisy third-party loggers
    silent_loggers = [
        "urllib3",
        "httpx",
        "httpcore",
        "openai",
        "litellm",
        "LiteLLM",
        "asyncio",
        "h2",
        "hpack",
        "boto3",
        "botocore",
        "s3transfer",
        "google_auth_oauthlib",
        "google.auth",
        "google.oauth2",
    ]
    for logger_name in silent_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured structlog logger

    Example:
        logger = get_logger(__name__)
        logger.info("user_action", user_id="123", action="login")
    """
    if name is None:
        import inspect

        frame = inspect.currentframe().f_back
        name = frame.f_globals.get("__name__", "unknown")

    return structlog.get_logger(name)
