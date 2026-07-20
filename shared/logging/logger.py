"""
Structured JSON logger for all platform services.
Every service imports get_logger() from here — never configure logging locally.
"""
import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from shared.config.settings import settings


def _add_service_name(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Inject service name into every log record."""
    event_dict.setdefault("service", settings.platform_name)
    event_dict.setdefault("env", settings.env)
    return event_dict


def _configure_structlog() -> None:
    """Configure structlog once at import time."""
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _add_service_name,
    ]

    if settings.env == "development":
        # Pretty console output for local development
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # JSON output for production (readable by log collectors)
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging to use structlog formatter
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(settings.log_level)

    # Silence noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


# Configure once on import
_configure_structlog()


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger for the given module.

    Usage:
        from shared.logging.logger import get_logger
        logger = get_logger(__name__)

        logger.info("Movie received", movie_id="abc", path="/downloads/movie.mkv")
        logger.error("Analysis failed", error=str(exc), movie_id="abc")
    """
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """
    Bind values to the current async context.
    All subsequent log calls in this context will include these values.

    Usage (in FastAPI middleware):
        bind_context(request_id="abc", user_id="123")
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear the current async log context."""
    structlog.contextvars.clear_contextvars()
