"""
Logging configuration for Femini API
"""

import structlog
import logging
import sys

# from .database import APIDatabase # This might cause circular import, let's just get settings directly
from femini_playwright import get_settings
import os

def setup_logging(log_level: str = "INFO"):
    """
    Setup structured logging for the API server with both console and file output
    """
    settings = get_settings()
    log_path = settings.log_path
    log_path.mkdir(parents=True, exist_ok=True)
    
    log_file = log_path / "api.log"

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding='utf-8')
    ]

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper()),
        handlers=handlers
    )
    
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False
    )
    
    logger = structlog.get_logger(__name__)
    logger.info("logging_configured", log_level=log_level, log_file=str(log_file))

def get_logger(name: str):
    """Get a logger instance"""
    return structlog.get_logger(name)