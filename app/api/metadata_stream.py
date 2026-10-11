"""
Phase 12 — Metadata Stream API Router.

Exports the metadata broadcaster WebSocket/SSE endpoints for real-time
detection, recognition, and tracking metadata streaming.
"""

from app.streaming.metadata_broadcaster import router

__all__ = ["router"]