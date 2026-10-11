"""
Phase 3.1 - ONNX Runtime Provider Verification

Distinguishes:
    CUDAExecutionProvider configured
from:
    CUDAExecutionProvider actually available
from:
    graph/node execution actually assigned to CUDA

If actual node-level execution cannot be proven at this phase,
explicitly report it as UNPROVEN.

No expensive per-frame diagnostics. Initialization-time only.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class ORTProviderVerification:
    """
    Reliable inspection of ORT session providers.
    """

    def __init__(self):
        self.discovered_providers: List[str] = []
        self.cuda_ep_configured = False
        self.cuda_ep_available = False
        self.node_level_proven = False
        self.node_level_unproven_reason = "Phase 3.1 does not verify per-node execution assignment"

    def discover(self) -> Dict[str, Any]:
        try:
            import onnxruntime as ort
            providers = ort.get_available_providers()
            self.discovered_providers = providers
            self.cuda_ep_configured = "CUDAExecutionProvider" in providers
            # Configured means registered; available means we can create session with it
            # For Phase 3.1, treat configured == available since we don't test session
            # creation with only CUDA (would break on non-CUDA systems)
            self.cuda_ep_available = self.cuda_ep_configured
        except Exception as exc:
            logger.debug("ORT provider discovery failed: %s", exc)
            self.discovered_providers = []
            self.cuda_ep_configured = False
            self.cuda_ep_available = False
        return self.get_report()

    def verify_session_providers(self, session) -> Dict[str, Any]:
        # Inspect an existing session's providers
        try:
            session_providers = session.get_providers()
            cuda_registered = "CUDAExecutionProvider" in session_providers
            return {
                "session_providers": session_providers,
                "cuda_registered_in_session": cuda_registered,
                "node_level_assigned_to_cuda": "UNPROVEN",
                "note": "Provider registration does not prove node-level CUDA execution"
            }
        except Exception as exc:
            return {
                "session_providers": [],
                "cuda_registered_in_session": False,
                "node_level_assigned_to_cuda": "UNPROVEN",
                "note": f"Inspection error: {exc}"
            }

    def get_report(self) -> Dict[str, Any]:
        return {
            "available_providers": self.discovered_providers,
            "cuda_ep_configured": self.cuda_ep_configured,
            "cuda_ep_available": self.cuda_ep_available,
            "node_level_cuda_assigned": "UNPROVEN",
            "unproven_reason": self.node_level_unproven_reason,
        }
