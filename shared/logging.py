import os

import structlog
from structlog._log_levels import NAME_TO_LEVEL


def setup_logging() -> None:
    """Configure structlog with JSON rendering for Lambda/CloudWatch."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    level_num = NAME_TO_LEVEL.get(log_level.lower(), 20)  # default INFO=20
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_num),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
