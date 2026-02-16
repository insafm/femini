"""
Femini Playwright - Production-ready async Gemini AI Studio automation

This package provides a complete refactoring of Selenium-based Gemini automation
into a production-optimized Playwright architecture with:

- Multiple Google credential support
- Async/await concurrency with proper queueing
- Docker-friendly design
- Structured logging
- Graceful resource management
- High-volume automation capabilities
"""

from .main import FeminiApp
from .queue_manager import Request, TaskResult
from .utils import setup_logging, get_logger

# Optional imports that require configuration
from .config import get_settings

def get_Settings():
    from .config import Settings
    return Settings

def get_Credential():
    from .config import Credential
    return Credential

__version__ = "1.0.0"
__all__ = [
    "FeminiApp",
    "Request",
    "TaskResult",
    "get_settings",
    "get_Settings",
    "get_Credential",
    "setup_logging",
    "get_logger"
]
