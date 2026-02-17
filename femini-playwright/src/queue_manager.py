import asyncio
import uuid
from typing import Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass
from .config import get_settings
from .credential_manager import CredentialManager
from .browser_manager import BrowserManager
import structlog

logger = structlog.get_logger(__name__)

@dataclass
class Request:
    """Represents a request to be processed"""
    task_id: str
    prompt: str
    is_image: bool = False
    force_json: bool = False
    force_text: bool = False
    reference_image_name: Optional[str] = None
    chat_id: Optional[str] = None
    account_id: Optional[str] = None
    credential_mode: Optional[str] = None
    return_image_data: bool = False  # Return base64-encoded image data
    filename_suffix: str = ""
    save_dir: Optional[str] = None
    download: bool = False
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class TaskResult:
    """Result of a processed task"""
    task_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    credential_key: Optional[str] = None
    processing_time: Optional[float] = None

class QueueManager:
    """Global queue for all incoming requests with worker pool"""

    def __init__(self, browser_mgr: BrowserManager, cred_mgr: CredentialManager):
        self.queue: asyncio.Queue = asyncio.Queue()  # Unlimited queue
        self.browser_mgr = browser_mgr
        self.cred_mgr = cred_mgr
        self.workers: list[asyncio.Task] = []
        self.running = False
        self.task_results: Dict[str, TaskResult] = {}
        self._result_lock = asyncio.Lock()
        
        # Client instances per credential (for persistent sessions)
        self.clients: Dict[str, Any] = {}  # credential_key -> GeminiClient
        self._client_lock = asyncio.Lock()
        self.credential_usage: Dict[str, int] = {}  # Track requests per credential

        # Stats
        self.stats = {
            "total_enqueued": 0,
            "total_processed": 0,
            "total_failed": 0,
            "active_workers": 0
        }

        self._cleanup_task: Optional[asyncio.Task] = None

        logger.info("queue_manager_initialized")

    async def enqueue_request(self, request: Request) -> str:
        """Add request to queue, returns task_id"""
        task_id = request.task_id
        await self.queue.put((task_id, request))

        async with self._result_lock:
            self.task_results[task_id] = TaskResult(
                task_id=task_id,
                success=False,
                result=None,
                credential_key=None
            )

        self.stats["total_enqueued"] += 1
        logger.info("request_enqueued",
                   task_id=task_id,
                   queue_size=self.queue.qsize(),
                   prompt_length=len(request.prompt))

        return task_id

    async def start_workers(self, num_workers: Optional[int] = None):
        """Start worker coroutines"""
        if num_workers is None:
            num_workers = len(self.cred_mgr.credentials)

        self.running = True
        logger.info("starting_workers", worker_count=num_workers)

        for i in range(num_workers):
            worker = asyncio.create_task(self._worker(f"worker-{i}"))
            self.workers.append(worker)

        # Start background results cleanup (every 10 min, purge > 1 hour)
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        self.stats["active_workers"] = num_workers
        logger.info("workers_started", active_workers=self.stats["active_workers"])

    async def stop_workers(self):
        """Stop all workers gracefully"""
        logger.info("stopping_workers")
        self.running = False

        # Wait for current tasks to complete
        await self.queue.join()

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()

        # Cancel workers
        for worker in self.workers:
            worker.cancel()

        # Wait for cancellation
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        self.stats["active_workers"] = 0

        # Cleanup persistent clients
        async with self._client_lock:
            for credential_key, client in self.clients.items():
                try:
                    await client.cleanup()
                    logger.info("client_cleaned_up", credential_key=credential_key)
                except Exception as e:
                    logger.warning("error_cleaning_up_client", 
                                 credential_key=credential.key,
                                 error=str(e))
            self.clients.clear()

        logger.info("workers_stopped")

    async def _worker(self, worker_id: str):
        """Worker processes requests from queue"""
        logger.info("worker_started", worker_id=worker_id)

        while self.running:
            try:
                # Get task from queue
                task_id, request = await self.queue.get()
                logger.debug("worker_picked_up_task", worker_id=worker_id, task_id=task_id)

                start_time = asyncio.get_event_loop().time()

                try:
                    # Get available credential (loop until one is free)
                    credential = None
                    while self.running:
                        credential = await self.cred_mgr.get_available_credential(
                            mode_override=request.credential_mode,
                            specific_key=request.account_id
                        )
                        if credential:
                            break
                        
                        logger.info("waiting_for_credential",
                                   task_id=task_id,
                                   worker_id=worker_id)
                        await self.cred_mgr.wait_for_available()
                    
                    if not credential:
                        # Worker stopping
                        continue

                    await self.cred_mgr.mark_busy(credential.key)

                    try:
                        # Get context (blocks if credential is busy)
                        context = await self.browser_mgr.get_context(credential.key)

                        try:
                            # Process request - this will be implemented in GeminiClient
                            result = await self._process_request(context, credential, request)

                            processing_time = asyncio.get_event_loop().time() - start_time
                            
                            # Check result-level success (Gemini logic level success)
                            is_success = False
                            error_msg = None
                            if isinstance(result, dict):
                                is_success = result.get("success", False)
                                error_msg = result.get("error")

                            # Store result
                            async with self._result_lock:
                                if is_success:
                                    self.task_results[task_id] = TaskResult(
                                        task_id=task_id,
                                        success=True,
                                        result=result,
                                        credential_key=credential.key,
                                        processing_time=processing_time
                                    )
                                    self.stats["total_processed"] += 1
                                    logger.info("request_completed",
                                            task_id=task_id,
                                            worker_id=worker_id,
                                            credential_key=credential.key,
                                            processing_time=f"{processing_time:.2f}s")
                                else:
                                    self.task_results[task_id] = TaskResult(
                                        task_id=task_id,
                                        success=False,
                                        error=error_msg or "Unknown worker error",
                                        result=result,
                                        credential_key=credential.key,
                                        processing_time=processing_time
                                    )
                                    self.stats["total_failed"] += 1
                                    logger.error("request_failed_logic",
                                            task_id=task_id,
                                            worker_id=worker_id,
                                            error=error_msg,
                                            processing_time=f"{processing_time:.2f}s")

                        finally:
                            await self.browser_mgr.release_context(credential.key)

                    finally:
                        await self.cred_mgr.mark_free(credential.key)

                except Exception as e:
                    processing_time = asyncio.get_event_loop().time() - start_time
                    error_msg = str(e)

                    # Store failed result
                    async with self._result_lock:
                        self.task_results[task_id] = TaskResult(
                            task_id=task_id,
                            success=False,
                            error=error_msg,
                            processing_time=processing_time
                        )

                    self.stats["total_failed"] += 1
                    logger.error("request_failed",
                               task_id=task_id,
                               worker_id=worker_id,
                               error=error_msg,
                               processing_time=f"{processing_time:.2f}s")

                finally:
                    self.queue.task_done()

            except asyncio.CancelledError:
                logger.info("worker_cancelled", worker_id=worker_id)
                break
            except Exception as e:
                logger.error("worker_error",
                           worker_id=worker_id,
                           error=str(e))
                await asyncio.sleep(1)  # Brief pause on error

        logger.info("worker_stopped", worker_id=worker_id)

    async def _get_or_create_client(self, context, credential):
        """Get existing client or create new one for credential"""
        async with self._client_lock:
            # Check if client exists and if its context is still valid (matches the fresh context)
            if credential.key in self.clients:
                client = self.clients[credential.key]
                if client.context != context:
                    logger.info("client_context_mismatch_recreating", credential_key=credential.key)
                    # Context was pruned or recreated, need new client
                    try:
                        await client.cleanup()
                    except Exception:
                        pass
                    del self.clients[credential.key]

            if credential.key not in self.clients:
                from .gemini_client import GeminiClient
                
                settings = get_settings()
                client = GeminiClient(context, credential, settings)
                await client.initialize()
                self.clients[credential.key] = client
                logger.info("client_created_for_credential", credential_key=credential.key)
            
            return self.clients[credential.key]

    async def _process_request(self, context, credential, request: Request) -> Any:
        """Process a single request using persistent GeminiClient"""
        # Increment usage count
        current_usage = self.credential_usage.get(credential.key, 0) + 1
        self.credential_usage[credential.key] = current_usage
        
        # Check for context recycling
        settings = get_settings()
        if current_usage > settings.max_requests_per_context:
            logger.info("recycling_context_limit_reached", 
                       credential_key=credential.key,
                       usage=current_usage,
                       limit=settings.max_requests_per_context)
            
            async with self._client_lock:
                # Cleanup existing client if exists
                if credential.key in self.clients:
                    try:
                        await self.clients[credential.key].cleanup()
                        del self.clients[credential.key]
                    except Exception as e:
                        logger.warning("error_cleaning_client_for_recycle", error=str(e))
                
                # Recreate browser context
                await self.browser_mgr.recreate_context(credential.key)
                
                # Update local context reference
                context = await self.browser_mgr.get_context(credential.key)
                
                # Reset usage counter
                self.credential_usage[credential.key] = 0

        # Get or create persistent client for this credential (will create new if recycled)
        client = await self._get_or_create_client(context, credential)
        
        # Process request without cleanup (client persists)
        result = await client.process_request(request)
        return result


    async def get_result(self, task_id: str) -> Optional[TaskResult]:
        """Get result for a task"""
        async with self._result_lock:
            return self.task_results.get(task_id)

    async def wait_for_result(self, task_id: str, timeout: float = 300.0) -> Optional[TaskResult]:
        """Wait for a task result with timeout"""
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            result = await self.get_result(task_id)
            if result and (result.success or result.error):
                return result
            await asyncio.sleep(0.1)

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        return {
            **self.stats,
            "queue_size": self.queue.qsize(),
            "pending_tasks": list(self.task_results.keys()),
            "worker_count": len(self.workers),
            "running": self.running
        }

    async def clear_completed_tasks(self, max_age: float = 3600.0):
        """Clear old completed tasks from memory"""
        current_time = asyncio.get_event_loop().time()

        async with self._result_lock:
            to_remove = []
            for task_id, result in self.task_results.items():
                if result.processing_time and (current_time - result.processing_time) > max_age:
                    to_remove.append(task_id)

            for task_id in to_remove:
                del self.task_results[task_id]

            if to_remove:
                logger.info("cleared_old_tasks", count=len(to_remove))

    async def _cleanup_loop(self):
        """Background loop to periodically clear old tasks (completed and failed)"""
        logger.info("cleanup_loop_started")
        try:
            while self.running:
                await asyncio.sleep(600)  # Run every 10 minutes
                # Automatically purges tasks older than 1 hour (3600s)
                await self.clear_completed_tasks(max_age=3600.0)
        except asyncio.CancelledError:
            logger.info("cleanup_loop_cancelled")
        except Exception as e:
            logger.error("cleanup_loop_error", error=str(e))

    async def health_check(self) -> bool:
        """Check if queue manager is healthy"""
        return self.running and len(self.workers) > 0