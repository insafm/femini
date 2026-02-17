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
        
        # Resource optimization
        self.last_activity: Dict[str, float] = {}  # {credential_key: timestamp}
        self._prune_task: Optional[asyncio.Task] = None
        self.prune_timeout = 300  # 5 minutes
        
        self._initialized = False
        self._shutdown_event = asyncio.Event()

    async def initialize(self):
        """Initialize browser manager (lazy loading)"""
        if self._initialized:
            return

        logger.info("initializing_browser_manager",
                   credential_count=len(self.credentials))

        try:
            self.playwright = await async_playwright().start()

            # Initialize semaphores (locks) but NOT contexts yet
            for cred in self.credentials:
                self.semaphores[cred.key] = asyncio.Semaphore(1)

            # Start background pruning task
            self._prune_task = asyncio.create_task(self._prune_loop())
            
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
        self.last_activity[credential.key] = asyncio.get_event_loop().time()
        
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
        """Get context for specific credential (lazy loaded)"""
        if not self._initialized:
            raise RuntimeError("BrowserManager not initialized")

        if credential_key not in self.semaphores:
            raise ValueError(f"Unknown credential key: {credential_key}")

        # Acquire semaphore (blocks if credential is busy)
        await self.semaphores[credential_key].acquire()
        
        try:
            # Lazy load: Create context if it doesn't exist
            if credential_key not in self.contexts:
                logger.info("lazy_loading_context", credential_key=credential_key)
                credential = next(c for c in self.credentials if c.key == credential_key)
                await self._create_context(credential)
            
            context = self.contexts.get(credential_key)
            if not context:
                raise RuntimeError(f"Failed to create context for: {credential_key}")
                
            # Update activity timestamp
            self.last_activity[credential_key] = asyncio.get_event_loop().time()
            
            logger.debug("context_acquired", credential_key=credential_key)
            return context
            
        except Exception as e:
            # Release semaphore if creation failed
            self.semaphores[credential_key].release()
            raise

    async def release_context(self, credential_key: str):
        """Release context semaphore"""
        if credential_key in self.semaphores:
            # Update activity timestamp on release too
            self.last_activity[credential_key] = asyncio.get_event_loop().time()
            self.semaphores[credential_key].release()
            logger.debug("context_released", credential_key=credential_key)

    async def recreate_context(self, credential_key: str):
        """Recreate context for a credential (useful for cleanup)"""
        if credential_key not in self.semaphores: # Check semaphores as contexts might be empty
             raise ValueError(f"Unknown credential key: {credential_key}")

        # Close existing context if it exists
        if credential_key in self.contexts:
            old_context = self.contexts[credential_key]
            try:
                await old_context.close()
            except Exception:
                pass
            del self.contexts[credential_key]

        # Find credential and recreate
        credential = next(c for c in self.credentials if c.key == credential_key)
        await self._create_context(credential)

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

    async def _prune_loop(self):
        """Background task to prune inactive contexts"""
        logger.info("prune_loop_started", timeout=self.prune_timeout)
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(60) # Check every minute
                
                now = asyncio.get_event_loop().time()
                to_prune = []
                
                # Identify inactive contexts
                for key, context in list(self.contexts.items()):
                    last_active = self.last_activity.get(key, 0)
                    if now - last_active > self.prune_timeout:
                        # Only prune if semaphore is free (not currently in use)
                        if self.semaphores[key]._value > 0:
                            to_prune.append(key)
                
                # Prune them
                for key in to_prune:
                    logger.info("pruning_inactive_context", credential_key=key, inactive_seconds=int(now - self.last_activity[key]))
                    context = self.contexts.pop(key, None)
                    if context:
                        await self._close_context_safe(key, context)
                        
        except asyncio.CancelledError:
            logger.info("prune_loop_cancelled")
        except Exception as e:
            logger.error("prune_loop_error", error=str(e))

    async def cleanup(self):
        """Graceful cleanup of all resources"""
        logger.info("starting_browser_cleanup")

        self._shutdown_event.set()
        
        # Cancel prune task
        if self._prune_task:
            self._prune_task.cancel()
            try:
                await self._prune_task
            except asyncio.CancelledError:
                pass

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