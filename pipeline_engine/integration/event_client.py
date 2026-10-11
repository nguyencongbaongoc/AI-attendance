"""
PipelineEngine Event Delivery Client

Submits CrossingEvents to Legacy Backend /api/v1/attendance/events
with idempotent delivery, bounded retry, and observable queue state.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class EventDeliveryConfig:
    """Configuration for event delivery client."""
    backend_base_url: str = "http://localhost:19146"
    api_key: str = ""
    queue_max_size: int = 1000
    delivery_interval: float = 1.0
    timeout: float = 10.0
    max_retries: int = 3
    base_retry_delay: float = 1.0
    max_retry_delay: float = 30.0
    retry_backoff: float = 2.0


@dataclass
class QueuedEvent:
    """Event queued for delivery with retry metadata."""
    event: Any  # CrossingEventRequest (avoid circular import)
    attempt: int = 0
    first_attempt_time: float = field(default_factory=time.time)
    last_error: Optional[str] = None


class EventDeliveryClient:
    """
    Delivers attendance events to Legacy Backend.
    
    Features:
    - Async non-blocking delivery
    - Bounded retry with exponential backoff
    - Local queue for offline buffering
    - Idempotent delivery (deduplication by event_id)
    - Observable queue state (pending/delivered/failed)
    - Error classification
    """
    
    def __init__(self, config: Optional[EventDeliveryConfig] = None):
        self.config = config or EventDeliveryConfig()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=self.config.queue_max_size)
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._pending_count = 0
        self._delivered_count = 0
        self._failed_count = 0
        self._lock = asyncio.Lock()
        self._delivered_event_ids: set = set()  # For idempotency
        self._delivered_ids_lock = asyncio.Lock()
        
    async def start(self) -> None:
        """Start the event delivery client."""
        if self._task is not None:
            return
            
        # Load API key from environment if not set
        if not self.config.api_key:
            self.config.api_key = os.environ.get("AI_WORKER_API_KEY")
            
        self._client = httpx.AsyncClient(
            base_url=self.config.backend_base_url,
            timeout=httpx.Timeout(self.config.timeout),
            headers={"X-API-Key": self.config.api_key} if self.config.api_key else {},
        )
        
        self._stop_event.clear()
        self._task = asyncio.create_task(self._delivery_loop())
        logger.info("Event delivery client started")
        
    async def stop(self) -> None:
        """Stop the event delivery client."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
                
        if self._client:
            await self._client.aclose()
            
        logger.info("Event delivery client stopped")
        
    async def submit_event(self, event: Any) -> bool:
        """
        Queue event for delivery.
        
        Returns True if queued, False if queue full (backpressure).
        """
        # Check idempotency
        event_id = getattr(event, 'event_id', None)
        if event_id:
            async with self._delivered_ids_lock:
                if event_id in self._delivered_event_ids:
                    logger.debug(f"Event {event_id} already delivered, skipping")
                    return True
        
        try:
            queued = QueuedEvent(event=event)
            self._queue.put_nowait(queued)
            async with self._lock:
                self._pending_count += 1
            return True
        except asyncio.QueueFull:
            logger.warning(f"Event delivery queue full ({self.config.queue_max_size}), dropping event")
            async with self._lock:
                self._failed_count += 1
            return False
            
    async def _delivery_loop(self) -> None:
        """Main delivery loop: process queued events."""
        while not self._stop_event.is_set():
            try:
                await self._process_queue()
            except Exception as e:
                logger.error(f"Event delivery loop error: {e}")
                
            await asyncio.sleep(self.config.delivery_interval)
            
    async def _process_queue(self) -> None:
        """Process all currently queued events."""
        while not self._queue.empty():
            try:
                queued = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
                
            success = await self._deliver_with_retry(queued)
            
            if success:
                # Mark as delivered for idempotency
                event_id = getattr(queued.event, 'event_id', None)
                if event_id:
                    async with self._delivered_ids_lock:
                        self._delivered_event_ids.add(event_id)
                        
                async with self._lock:
                    self._delivered_count += 1
                    self._pending_count -= 1
            else:
                # Re-queue for retry if not exceeded max retries
                if queued.attempt < self.config.max_retries:
                    queued.attempt += 1
                    try:
                        await self._queue.put(queued)
                    except asyncio.QueueFull:
                        logger.error(f"Queue full on retry, dropping event {getattr(queued.event, 'event_id', 'unknown')}")
                        async with self._lock:
                            self._failed_count += 1
                            self._pending_count -= 1
                else:
                    logger.error(f"Event {getattr(queued.event, 'event_id', 'unknown')} failed after {queued.attempt} attempts: {queued.last_error}")
                    async with self._lock:
                        self._failed_count += 1
                        self._pending_count -= 1
                        
    async def _deliver_with_retry(self, queued: QueuedEvent) -> bool:
        """Deliver single event with retry logic."""
        for attempt in range(queued.attempt, self.config.max_retries + 1):
            try:
                # Convert event to dict if it's a Pydantic model
                if hasattr(queued.event, 'model_dump'):
                    payload = queued.event.model_dump()
                elif hasattr(queued.event, 'dict'):
                    payload = queued.event.dict()
                else:
                    payload = queued.event
                    
                response = await self._client.post(
                    "/api/v1/attendance/events",
                    json=payload
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        logger.debug(f"Event {getattr(queued.event, 'event_id', 'unknown')} delivered successfully")
                        return True
                    else:
                        queued.last_error = data.get("message", "Unknown error")
                        logger.warning(f"Event delivery rejected: {queued.last_error}")
                        # Don't retry on validation errors (400)
                        if response.status_code == 400:
                            return False
                elif response.status_code == 401:
                    logger.error("Event delivery: Invalid API key")
                    return False
                elif response.status_code == 409:
                    # Conflict - duplicate event, consider delivered
                    logger.info(f"Event {getattr(queued.event, 'event_id', 'unknown')} already exists (idempotent)")
                    return True
                else:
                    queued.last_error = f"HTTP {response.status_code}: {response.text}"
                    
            except httpx.TimeoutException:
                queued.last_error = "Timeout"
            except httpx.ConnectError:
                queued.last_error = "Connection failed"
            except Exception as e:
                queued.last_error = str(e)
                
            if attempt < self.config.max_retries:
                delay = min(
                    self.config.base_retry_delay * (self.config.retry_backoff ** attempt),
                    self.config.max_retry_delay
                )
                logger.warning(f"Event delivery attempt {attempt + 1} failed: {queued.last_error}, retrying in {delay:.1f}s")
                await asyncio.sleep(delay)
            else:
                logger.error(f"Event delivery failed after {attempt + 1} attempts: {queued.last_error}")
                
        return False
        
    def get_stats(self) -> Dict[str, Any]:
        """Get delivery statistics."""
        return {
            "pending": self._pending_count,
            "delivered": self._delivered_count,
            "failed": self._failed_count,
            "queue_depth": self._queue.qsize(),
            "queue_max": self.config.queue_max_size,
            "queue_utilization_pct": (self._queue.qsize() / self.config.queue_max_size) * 100,
        }
        
    def is_healthy(self) -> bool:
        """Check if delivery client is healthy."""
        return (
            self._client is not None and
            not self._stop_event.is_set() and
            self._queue.qsize() < self.config.queue_max_size * 0.9  # Not near capacity
        )


def create_event_client(config: Optional[EventDeliveryConfig] = None) -> EventDeliveryClient:
    """Factory function to create event delivery client."""
    return EventDeliveryClient(config)


async def setup_event_delivery(
    worker_id: str,
    backend_base_url: str = "http://localhost:19146",
    config: Optional[EventDeliveryConfig] = None
) -> EventDeliveryClient:
    """Set up event delivery for a worker."""
    if config is None:
        config = EventDeliveryConfig()
    config.backend_base_url = backend_base_url
    # API key will be loaded from env in start()
    
    client = create_event_client(config)
    await client.start()
    return client