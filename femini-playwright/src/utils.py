import os
import sys
import logging
import structlog
from pathlib import Path
from .config import get_settings

def setup_logging():
    """Setup structured logging with file and console output"""
    settings = get_settings()

    # Create logs directory
    log_path = settings.log_path
    log_path.mkdir(parents=True, exist_ok=True)

    # Configure standard logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path / "femini.log", encoding='utf-8')
        ]
    )

    # Configure structlog
    shared_processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.log_level.upper() == "DEBUG":
        # In debug mode, log to console with colors and formatting
        console_renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # In production, use JSON for console (good for log aggregation)
        console_renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [
            # Console output
            console_renderer,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Suppress noisy loggers
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    logger = structlog.get_logger(__name__)
    logger.info("logging_configured",
               level=settings.log_level,
               log_path=str(log_path))

def get_logger(name: str):
    """Get a structured logger instance"""
    return structlog.get_logger(name)

# Global logger instance
logger = get_logger(__name__)