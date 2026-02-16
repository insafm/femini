#!/usr/bin/env python3
"""
Femini Playwright - Production-ready async Gemini AI Studio automation
"""

import asyncio
import signal
import sys
from typing import Optional
from .utils import setup_logging, get_logger
from .browser_manager import BrowserManager
from .credential_manager import CredentialManager
from .queue_manager import QueueManager, Request
from .config import get_settings

logger = get_logger(__name__)

class FeminiApp:
    """Main application class"""

    def __init__(self):
        self.browser_mgr: Optional[BrowserManager] = None
        self.cred_mgr: Optional[CredentialManager] = None
        self.queue_mgr: Optional[QueueManager] = None
        self.running = False

    async def initialize(self):
        """Initialize all components"""
        settings = get_settings()
        logger.info("initializing_femini_app",
                   credentials=len(settings.credentials),
                   mode=settings.credential_mode)

        # Initialize credential manager
        self.cred_mgr = CredentialManager(settings.credentials, settings.credential_mode)

        # Initialize browser manager
        self.browser_mgr = BrowserManager(settings.credentials, settings)

        # Initialize queue manager
        self.queue_mgr = QueueManager(self.browser_mgr, self.cred_mgr)

        # Initialize browser
        await self.browser_mgr.initialize()

        # Start workers
        await self.queue_mgr.start_workers()

        logger.info("femini_app_initialized")

    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("shutting_down_femini_app")

        if self.queue_mgr:
            await self.queue_mgr.stop_workers()

        if self.browser_mgr:
            await self.browser_mgr.cleanup()

        logger.info("femini_app_shutdown_complete")

    async def submit_request(self, request: Request) -> str:
        """Submit a request to the queue"""
        logger.info("submitting_request", prompt=request.prompt[:50], is_image=request.is_image)
        if not self.queue_mgr:
            raise RuntimeError("Queue manager not initialized")

        task_id = await self.queue_mgr.enqueue_request(request)
        return task_id

    async def get_result(self, task_id: str):
        """Get result for a task"""
        if not self.queue_mgr:
            raise RuntimeError("Queue manager not initialized")

        return await self.queue_mgr.get_result(task_id)

    async def wait_for_result(self, task_id: str, timeout: float = 300.0):
        """Wait for a task result"""
        logger.info("waiting_for_result", task_id=task_id, timeout=timeout)
        if not self.queue_mgr:
            raise RuntimeError("Queue manager not initialized")

        return await self.queue_mgr.wait_for_result(task_id, timeout)

    def get_completed_result(self, task_id: str):
        """
        Non-blocking check for completed result
        Returns result if available, None otherwise
        Used by API server for polling
        """
        if not self.queue_mgr:
            raise RuntimeError("Queue manager not initialized")

        result = self.queue_mgr.task_results.get(task_id)
        # Only return if actually completed (success=True or has error)
        if result and (result.success or result.error):
            return result
        return None

    @property
    def queue_manager(self):
        """Expose queue manager for API access"""
        return self.queue_mgr

    def get_stats(self):
        """Get application statistics"""
        return {
            "credentials": self.cred_mgr.get_stats() if self.cred_mgr else None,
            "browser": self.browser_mgr.get_stats() if self.browser_mgr else None,
            "queue": self.queue_mgr.get_stats() if self.queue_mgr else None,
        }

# Global app instance
app: Optional[FeminiApp] = None

async def main():
    """Main entry point"""
    global app

    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info("signal_received", signal=signum)
        if app:
            asyncio.create_task(app.shutdown())

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Initialize app
        app = FeminiApp()
        await app.initialize()

        settings = get_settings()
        logger.info("femini_app_started",
                   api_enabled=False,
                   credentials=len(settings.credentials))

        # Keep running until shutdown
        while app.running:
            await asyncio.sleep(1)

    except Exception as e:
        logger.error("fatal_error", error=str(e))
        sys.exit(1)
    finally:
        if app:
            await app.shutdown()

if __name__ == "__main__":
    # Setup logging first
    setup_logging()

    # Run main
    asyncio.run(main())