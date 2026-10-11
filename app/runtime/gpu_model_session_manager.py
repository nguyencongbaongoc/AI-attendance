"""
Phase 3.1 - Model Session Management

Centralized model/session management layer.
- Reuse model/session instances
- Avoid per-frame model creation
- Avoid unnecessary per-camera duplication
- Support CAM1 and CAM2
- Make GPU device selection explicit
- Preserve existing model configuration
- Preserve existing fallback behavior
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class ModelSessionManager:
    """
    Manages shared GPU model/session resources.
    Does NOT change inference semantics yet.
    Does NOT migrate individual models yet unless required for foundation.
    """

    def __init__(self, device_index: int = 0):
        self.device_index = device_index
        self.sessions: Dict[str, Any] = {}  # key -> session or model reference
        self.config: Dict[str, Any] = {}

    def configure_camera(self, camera_id: str, session_config: Dict[str, Any]):
        # Preserve existing configuration; add explicit device selection
        self.config[camera_id] = session_config
        # Make GPU device selection explicit
        session_config.setdefault("gpu_device_index", self.device_index)
        session_config.setdefault("use_cuda_ep", True)

    def get_session_key(self, model_name: str, camera_id: Optional[str] = None) -> str:
        # Shared resources where architecture permits; avoid per-camera duplication
        return f"{model_name}:{self.device_index}"

    def get_or_create_session(self, model_name: str, camera_id: Optional[str] = None):
        # In Phase 3.1 we do NOT create actual ORT sessions here unless needed.
        # This is the contract layer.
        key = self.get_session_key(model_name, camera_id)
        if key in self.sessions:
            return self.sessions[key]
        # Placeholder for future session creation (Phase 3.2+)
        session_ref = {"key": key, "model_name": model_name, "device_index": self.device_index, "created": False}
        self.sessions[key] = session_ref
        return session_ref

    def has_session(self, model_name: str, camera_id: Optional[str] = None) -> bool:
        key = self.get_session_key(model_name, camera_id)
        return key in self.sessions

    def get_all_session_keys(self) -> list:
        return list(self.sessions.keys())

    def get_config_for_camera(self, camera_id: str) -> Optional[Dict[str, Any]]:
        return self.config.get(camera_id)
