import asyncio
import signal
from typing import Dict, Optional, List
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import structlog

logger = structlog.get_logger(__name__)

class BrowserManager:
    """Manages browser contexts per credential with pooling and lifecycle management"""

    def __init__(self, credentials, settings):
        self.credentials = credentials
        self.settings = settings
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.contexts: Dict[str, BrowserContext] = {}  # {credential_key: BrowserContext}
        self.semaphores: Dict[str, asyncio.Semaphore] = {}  # {credential_key: Semaphore}
        self._initialized = False
        self._shutdown_event = asyncio.Event()

    async def initialize(self):
        """Initialize persistent browser contexts (one per credential)"""
        if self._initialized:
            return

        logger.info("initializing_browser_manager",
                   credential_count=len(self.credentials))

        try:
            self.playwright = await async_playwright().start()

            # Create persistent context per credential (replaces browser + context)
            for cred in self.credentials:
                await self._create_context(cred)
                # Semaphore ensures only 1 concurrent request per credential
                self.semaphores[cred.key] = asyncio.Semaphore(1)

            self._initialized = True
            logger.info("browser_manager_initialized_successfully")

        except Exception as e:
            logger.error("browser_manager_initialization_failed", error=str(e))
            await self.cleanup()
            raise

    async def _create_context(self, credential) -> BrowserContext:
        """Create persistent browser context for a credential"""
        user_data_path = self.settings.get_user_data_path(credential.key)

        # Use launch_persistent_context for automatic user_data persistence
        context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_path),
            headless=self.settings.headless,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ignore_https_errors=True,
            viewport={"width": 1800, "height": 850},
            args=[
                "--no-sandbox",
                "--disable-notifications",
                "--disable-blink-features=AutomationControlled",
                "--disable-extensions",
                "--disable-plugins-discovery",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--start-maximized",
                "--window-size=1800,850",
                "--force-device-scale-factor=1",
            ]
        )

        # Set up context-level event handlers
        context.on("page", self._on_new_page)

        self.contexts[credential.key] = context
        logger.info("persistent_context_created", 
                   credential_key=credential.key,
                   user_data_path=str(user_data_path))
        return context

    async def _on_new_page(self, page: Page):
        """Handle new page creation"""
        # Add stealth measures to each new page
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

    async def get_context(self, credential_key: str) -> BrowserContext:
        """Get context for specific credential with semaphore control"""
        if not self._initialized:
            raise RuntimeError("BrowserManager not initialized")

        if credential_key not in self.semaphores:
            raise ValueError(f"Unknown credential key: {credential_key}")

        # Acquire semaphore (blocks if credential is busy)
        await self.semaphores[credential_key].acquire()

        context = self.contexts.get(credential_key)
        if not context:
            raise RuntimeError(f"Context not found for credential: {credential_key}")

        logger.debug("context_acquired", credential_key=credential_key)
        return context

    async def release_context(self, credential_key: str):
        """Release context semaphore"""
        if credential_key in self.semaphores:
            self.semaphores[credential_key].release()
            logger.debug("context_released", credential_key=credential_key)

    async def recreate_context(self, credential_key: str):
        """Recreate context for a credential (useful for cleanup)"""
        if credential_key not in self.contexts:
            raise ValueError(f"Unknown credential key: {credential_key}")

        # Close existing context
        old_context = self.contexts[credential_key]
        await old_context.close()

        # Find credential and recreate
        credential = next(c for c in self.credentials if c.key == credential_key)
        new_context = await self._create_context(credential)

        logger.info("context_recreated", credential_key=credential_key)

    async def get_page(self, credential_key: str) -> Page:
        """Get a fresh page for the credential"""
        context = await self.get_context(credential_key)
        try:
            page = await context.new_page()
            return page
        except Exception:
            await self.release_context(credential_key)
            raise

    async def cleanup(self):
        """Graceful cleanup of all resources"""
        logger.info("starting_browser_cleanup")

        self._shutdown_event.set()

        # Close all contexts
        close_tasks = []
        for cred_key, context in self.contexts.items():
            close_tasks.append(self._close_context_safe(cred_key, context))

        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

        # Close browser
        if self.browser:
            try:
                await self.browser.close()
                logger.debug("browser_closed")
            except Exception as e:
                logger.warning("error_closing_browser", error=str(e))

        # Stop playwright
        if self.playwright:
            try:
                await self.playwright.stop()
                logger.debug("playwright_stopped")
            except Exception as e:
                logger.warning("error_stopping_playwright", error=str(e))

        self._initialized = False
        logger.info("browser_cleanup_completed")

    async def _close_context_safe(self, cred_key: str, context: BrowserContext):
        """Safely close a context"""
        try:
            await context.close()
            logger.debug("context_closed", credential_key=cred_key)
        except Exception as e:
            logger.warning("error_closing_context",
                          credential_key=cred_key,
                          error=str(e))


    def get_stats(self) -> Dict:
        """Get browser manager statistics"""
        semaphore_states = {}
        for cred_key, semaphore in self.semaphores.items():
            semaphore_states[cred_key] = semaphore._value

        return {
            "initialized": self._initialized,
            "total_credentials": len(self.credentials),
            "credential_keys": list(self.contexts.keys()),
            "semaphore_states": semaphore_states,
            "shutdown_requested": self._shutdown_event.is_set()
        }

    async def health_check(self) -> bool:
        """Check if browser manager is healthy"""
        if not self._initialized or not self.browser:
            return False

        try:
            # Try to create a test page
            page = await self.browser.new_page()
            await page.close()
            return True
        except Exception:
            return False