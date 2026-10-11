"""
Phase 7 — API Key Cache for Hot Rotation Support.

Provides thread-safe API key caching with TTL to support hot rotation
without process restart.
"""

from __future__ import annotations

import os
import time
import threading
from typing import Optional


class APIKeyCache:
    """Thread-safe API key cache with TTL for hot rotation."""
    
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[str, float]] = {}  # key_name -> (value, expiry)
        self._lock = threading.RLock()
    
    def get(self, key_name: str) -> Optional[str]:
        now = time.time()
        with self._lock:
            if key_name in self._cache:
                value, expiry = self._cache[key_name]
                if now < expiry:
                    return value
                else:
                    del self._cache[key_name]
            
            # Load from environment
            value = os.environ.get(key_name)
            if value:
                self._cache[key_name] = (value, now + self.ttl_seconds)
            return value
    
    def invalidate(self, key_name: str) -> None:
        with self._lock:
            if key_name in self._cache:
                del self._cache[key_name]
    
    def invalidate_all(self) -> None:
        with self._lock:
            self._cache.clear()
    
    def set_ttl(self, ttl_seconds: int) -> None:
        with self._lock:
            self.ttl_seconds = ttl_seconds


# Global API key cache instance
_api_key_cache: Optional[APIKeyCache] = None
_cache_lock = threading.Lock()


def get_api_key_cache() -> APIKeyCache:
    """Get or create the global API key cache."""
    global _api_key_cache
    if _api_key_cache is None:
        with _cache_lock:
            if _api_key_cache is None:
                # Default TTL, will be updated when settings are loaded
                _api_key_cache = APIKeyCache(ttl_seconds=300)
    return _api_key_cache


def init_api_key_cache(ttl_seconds: int = 300) -> APIKeyCache:
    """Initialize the API key cache with a specific TTL."""
    global _api_key_cache
    with _cache_lock:
        _api_key_cache = APIKeyCache(ttl_seconds=ttl_seconds)
    return _api_key_cache