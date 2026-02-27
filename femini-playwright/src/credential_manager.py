import asyncio
import random
from typing import List, Dict, Optional
import structlog
from .config import get_settings

logger = structlog.get_logger(__name__)

class CredentialManager:
    """Manages multiple Google credentials and selection strategy"""

    def __init__(self, credentials, mode: str = "random"):
        self.credentials = credentials
        self.mode = mode  # random, round_robin, default, least_busy
        self.usage_count: Dict[str, int] = {cred.key: 0 for cred in credentials}
        self.active_tasks: Dict[str, int] = {cred.key: 0 for cred in credentials}
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)
        self._round_robin_index = 0

        logger.info("credential_manager_initialized",
                   credential_count=len(credentials),
                   mode=mode,
                   credential_keys=[c.key for c in credentials])

    async def get_credential(self):
        """Get credential based on selection mode"""
        async with self._lock:
            if self.mode == "random":
                return self._random_select()
            elif self.mode == "round_robin":
                return self._round_robin_select()
            elif self.mode == "least_busy":
                return self._least_busy_select()
            else:  # default
                return self._default_select()

    def _random_select(self):
        """Random credential selection"""
        credential = random.choice(self.credentials)
        self.usage_count[credential.key] += 1
        logger.debug("credential_selected_random", credential_key=credential.key)
        return credential

    def _round_robin_select(self):
        """Round-robin credential selection"""
        credential = self.credentials[self._round_robin_index % len(self.credentials)]
        self._round_robin_index += 1
        self.usage_count[credential.key] += 1
        logger.debug("credential_selected_round_robin",
                    credential_key=credential.key,
                    index=self._round_robin_index - 1)
        return credential

    def _least_busy_select(self):
        """Select credential with least active tasks"""
        # Find credential with minimum active tasks
        min_active = min(self.active_tasks.values())
        candidates = [cred for cred in self.credentials
                     if self.active_tasks[cred.key] == min_active]

        # If tie, choose randomly among candidates
        credential = random.choice(candidates)
        self.usage_count[credential.key] += 1
        logger.debug("credential_selected_least_busy",
                    credential_key=credential.key,
                    active_tasks=min_active)
        return credential

    def _default_select(self):
        """Select default credential"""
        settings = get_settings()
        try:
            credential = self.credentials[settings.default_credential_index]
        except IndexError:
            logger.warning("invalid_default_credential_index",
                          index=settings.default_credential_index,
                          available=len(self.credentials))
            credential = self.credentials[0]  # Fallback to first

        self.usage_count[credential.key] += 1
        logger.debug("credential_selected_default", credential_key=credential.key)
        return credential

    async def mark_busy(self, credential_key: str):
        """Mark credential as busy (increment active tasks)"""
        async with self._lock:
            self.active_tasks[credential_key] += 1
            logger.debug("credential_marked_busy",
                        credential_key=credential_key,
                        active_tasks=self.active_tasks[credential_key])

    def _mark_busy_locked(self, credential_key: str):
        """Mark busy without acquiring lock (must already hold self._lock)"""
        self.active_tasks[credential_key] += 1
        logger.debug("credential_marked_busy",
                    credential_key=credential_key,
                    active_tasks=self.active_tasks[credential_key])

    async def mark_free(self, credential_key: str):
        """Mark credential as free (decrement active tasks)"""
        async with self._lock:
            if self.active_tasks[credential_key] > 0:
                self.active_tasks[credential_key] -= 1
            logger.debug("credential_marked_free",
                        credential_key=credential_key,
                        active_tasks=self.active_tasks[credential_key])
            self._condition.notify_all()

    def get_stats(self) -> Dict:
        """Get credential usage statistics"""
        return {
            "total_credentials": len(self.credentials),
            "mode": self.mode,
            "usage_count": self.usage_count.copy(),
            "active_tasks": self.active_tasks.copy(),
            "credential_keys": [c.key for c in self.credentials]
        }

    async def get_available_credential(self, mode_override: Optional[str] = None, specific_key: Optional[str] = None):
        """Get a credential that has available capacity and atomically mark it busy."""
        async with self._lock:
            settings = get_settings()
            
            # Helper function to check capacity
            def has_capacity(cred):
                return self.active_tasks[cred.key] < settings.max_concurrent_per_credential

            # Strategy 1: Specific key requested
            if specific_key:
                credential = next((c for c in self.credentials if c.key == specific_key), None)
                if not credential:
                    logger.warning("specific_credential_not_found", key=specific_key)
                    return None
                
                if has_capacity(credential):
                    self._mark_busy_locked(credential.key)
                    return credential
                else:
                    logger.debug("specific_credential_busy", key=specific_key)
                    return None

            # Strategy 2: Determine mode (override or configured)
            mode = mode_override if mode_override else self.mode

            # Filter credentials with capacity
            available = [cred for cred in self.credentials if has_capacity(cred)]

            if not available:
                return None

            # Use selection mode
            selected = None
            if mode == "random":
                selected = random.choice(available)
            elif mode == "least_busy":
                selected = min(available, key=lambda c: self.active_tasks[c.key])
            elif mode == "round_robin":
                available_keys = [c.key for c in available]
                for _ in range(len(self.credentials)):
                    candidate = self.credentials[self._round_robin_index % len(self.credentials)]
                    self._round_robin_index += 1
                    if candidate.key in available_keys:
                        selected = candidate
                        break
                if selected is None:
                    selected = available[0]  # Fallback
            else:  # default
                default_index = settings.default_credential_index
                try:
                    default_cred = self.credentials[default_index]
                except IndexError:
                    default_cred = self.credentials[0]
                
                if default_cred.key in [c.key for c in available]:
                    selected = default_cred
                else:
                    selected = None  # Default is busy — return None (strict)

            if selected is not None:
                # Atomically mark busy before releasing lock
                self._mark_busy_locked(selected.key)
            
            return selected

    async def wait_for_available(self):
        """Wait until a credential might be available"""
        async with self._condition:
            await self._condition.wait()