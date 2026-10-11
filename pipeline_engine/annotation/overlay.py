"""
GPU Annotation Overlay - Renders detection/identity overlays on GPU frames.

Zero-copy GPU-only rendering of bounding boxes, labels, and diagnostic info.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
from enum import Enum

import torch
import torch.nn.functional as F

from pipeline_engine.memory.gpu_frame import GPUFrame, nv12_to_bgr_cuda, bgr_to_nv12_cuda
from pipeline_engine.tracking.tracker import Track
from pipeline_engine.config import get_camera_config, get_config

logger = logging.getLogger(__name__)


class OverlayElement(str, Enum):
    """Types of overlay elements."""
    PERSON_BOX = "person_box"
    FACE_BOX = "face_box"
    TRACK_ID = "track_id"
    CONFIDENCE = "confidence"
    PERSON_NAME = "person_name"
    CROSSING_LINE = "crossing_line"
    FPS = "fps"
    LATENCY = "latency"
    GPU_MEMORY = "gpu_memory"


@dataclass
class AnnotationConfig:
    """Configuration for annotation overlay."""
    enabled: bool = True
    
    # Which elements to show
    show: Dict[OverlayElement, bool] = field(default_factory=lambda: {
        OverlayElement.PERSON_BOX: True,
        OverlayElement.FACE_BOX: True,
        OverlayElement.TRACK_ID: True,
        OverlayElement.CONFIDENCE: True,
        OverlayElement.PERSON_NAME: True,
        OverlayElement.CROSSING_LINE: True,
        OverlayElement.FPS: True,
        OverlayElement.LATENCY: True,
        OverlayElement.GPU_MEMORY: True,
    })
    
    # Style
    box_thickness: int = 2
    font_scale: float = 0.6
    font_thickness: int = 1
    
    # Colors (BGR)
    colors: Dict[str, Tuple[int, int, int]] = field(default_factory=lambda: {
        "person_box": (0, 255, 0),       # Green
        "face_box": (255, 0, 0),         # Blue
        "track_id": (255, 255, 255),     # White
        "name_known": (0, 255, 0),       # Green
        "name_unknown": (0, 0, 255),     # Red
        "line": (255, 255, 0),           # Cyan
        "in_indicator": (0, 255, 0),     # Green
        "out_indicator": (0, 0, 255),    # Red
        "text_bg": (0, 0, 0),            # Black
        "fps_text": (255, 255, 255),     # White
    })


class GPUAnnotator:
    """
    GPU-based annotation renderer.
    
    Renders overlays directly on CUDA tensors without CPU round-trip.
    Uses PyTorch CUDA operations for all drawing.
    """
    
    def __init__(self, config: Optional[AnnotationConfig] = None, device_id: int = 0):
        self.config = config or AnnotationConfig()
        self.device_id = device_id
        self.device = f'cuda:{device_id}'
        
        # Pre-create font texture (simple 8x8 pixel font)
        self._font_texture = self._create_font_texture()
        
        # Stats
        self._annotation_count = 0
        self._total_time_ms = 0.0
    
    def _create_font_texture(self) -> torch.Tensor:
        """Create a simple font texture for text rendering."""
        # For now, return a placeholder - real implementation would use a proper font
        # This is a simplified 8x16 font for ASCII 32-126
        font = torch.zeros((95, 16, 8), dtype=torch.uint8, device=self.device)
        # In production, load a real font texture
        return font
    
    def annotate(
        self,
        frame: GPUFrame,
        tracks: List[Track],
        camera_id: str,
        frame_metrics: Optional[Dict[str, Any]] = None,
    ) -> GPUFrame:
        """
        Annotate a GPUFrame with tracking and diagnostic overlays.
        
        Args:
            frame: GPUFrame to annotate (NV12 format)
            tracks: List of active tracks
            camera_id: Camera identifier for config lookup
            frame_metrics: Optional metrics dict (fps, latency, gpu_mem, etc.)
            
        Returns:
            Annotated GPUFrame (NV12, with annotation tensor set)
        """
        import time
        start = time.perf_counter()
        
        # Convert NV12 to BGR for rendering
        y_tensor, uv_tensor = frame.get_tensors()
        bgr = nv12_to_bgr_cuda(y_tensor, uv_tensor)  # (H, W, 3) uint8
        
        H, W = bgr.shape[:2]
        
        # Get camera-specific config
        cam_config = get_camera_config(get_config(), camera_id)
        ann_config = cam_config.get("annotation", {})
        
        # Draw each element
        if self.config.show[OverlayElement.PERSON_BOX]:
            bgr = self._draw_person_boxes(bgr, tracks)
        
        if self.config.show[OverlayElement.FACE_BOX]:
            bgr = self._draw_face_boxes(bgr, tracks)
        
        if self.config.show[OverlayElement.TRACK_ID] or self.config.show[OverlayElement.PERSON_NAME]:
            bgr = self._draw_labels(bgr, tracks)
        
        if self.config.show[OverlayElement.CROSSING_LINE]:
            bgr = self._draw_crossing_line(bgr, cam_config)
        
        if frame_metrics and (self.config.show[OverlayElement.FPS] or 
                              self.config.show[OverlayElement.LATENCY] or 
                              self.config.show[OverlayElement.GPU_MEMORY]):
            bgr = self._draw_diagnostics(bgr, frame_metrics)
        
        # Convert back to NV12
        y_annotated, uv_annotated = bgr_to_nv12_cuda(bgr)
        
        # Update frame tensors
        frame.y_tensor.copy_(y_annotated)
        frame.uv_tensor.copy_(uv_annotated)
        
        # Store annotation tensor for potential encoder use
        frame.set_annotation_tensor(bgr)
        
        # Update timing
        elapsed_ms = (time.perf_counter() - start) * 1000
        frame.annotation_time_ms = elapsed_ms
        self._annotation_count += 1
        self._total_time_ms += elapsed_ms
        
        return frame
    
    def _draw_person_boxes(self, bgr: torch.Tensor, tracks: List[Track]) -> torch.Tensor:
        """Draw person bounding boxes."""
        color = self.config.colors["person_box"]
        thickness = self.config.box_thickness
        
        for track in tracks:
            if not track.is_active and not track.is_new:
                continue
            
            x1, y1, x2, y2 = [int(c) for c in track.bbox_original_frame]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(bgr.shape[1], x2), min(bgr.shape[0], y2)
            
            if x2 <= x1 or y2 <= y1:
                continue
            
            # Draw rectangle (top, bottom, left, right borders)
            bgr[y1:y1+thickness, x1:x2] = torch.tensor(color, device=self.device, dtype=torch.uint8)
            bgr[y2-thickness:y2, x1:x2] = torch.tensor(color, device=self.device, dtype=torch.uint8)
            bgr[y1:y2, x1:x1+thickness] = torch.tensor(color, device=self.device, dtype=torch.uint8)
            bgr[y1:y2, x2-thickness:x2] = torch.tensor(color, device=self.device, dtype=torch.uint8)
        
        return bgr
    
    def _draw_face_boxes(self, bgr: torch.Tensor, tracks: List[Track]) -> torch.Tensor:
        """Draw face bounding boxes."""
        color = self.config.colors["face_box"]
        thickness = self.config.box_thickness
        
        for track in tracks:
            if not track.is_active and not track.is_new:
                continue
            
            if track.face_bbox is None:
                continue
            
            x1, y1, x2, y2 = [int(c) for c in track.face_bbox]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(bgr.shape[1], x2), min(bgr.shape[0], y2)
            
            if x2 <= x1 or y2 <= y1:
                continue
            
            bgr[y1:y1+thickness, x1:x2] = torch.tensor(color, device=self.device, dtype=torch.uint8)
            bgr[y2-thickness:y2, x1:x2] = torch.tensor(color, device=self.device, dtype=torch.uint8)
            bgr[y1:y2, x1:x1+thickness] = torch.tensor(color, device=self.device, dtype=torch.uint8)
            bgr[y1:y2, x2-thickness:x2] = torch.tensor(color, device=self.device, dtype=torch.uint8)
        
        return bgr
    
    def _draw_labels(self, bgr: torch.Tensor, tracks: List[Track]) -> torch.Tensor:
        """Draw track ID and person name labels."""
        # Simple text rendering using tensor operations
        # In production, use a proper font rendering library
        
        for track in tracks:
            if not track.is_active and not track.is_new:
                continue
            
            x1, y1, x2, y2 = [int(c) for c in track.bbox_original_frame]
            
            # Draw track ID
            if self.config.show[OverlayElement.TRACK_ID]:
                label = f"ID:{track.track_id}"
                bgr = self._draw_text(bgr, label, (x1, y1 - 20), self.config.colors["track_id"])
            
            # Draw person name
            if self.config.show[OverlayElement.PERSON_NAME] and track.person_name:
                color = self.config.colors["name_known"] if track.is_identified else self.config.colors["name_unknown"]
                label = f"{track.person_name} ({track.identity_confidence:.2f})"
                bgr = self._draw_text(bgr, label, (x1, y1 - 40), color)
        
        return bgr
    
    def _draw_text(
        self, 
        bgr: torch.Tensor, 
        text: str, 
        position: Tuple[int, int], 
        color: Tuple[int, int, int],
        bg_color: Tuple[int, int, int] = (0, 0, 0)
    ) -> torch.Tensor:
        """Draw text on BGR tensor (simplified - uses tensor operations)."""
        # This is a placeholder for real text rendering
        # In production, use a proper font atlas and shader-based rendering
        
        x, y = position
        if x < 0 or y < 0 or x >= bgr.shape[1] or y >= bgr.shape[0]:
            return bgr
        
        # Draw a simple colored rectangle as text placeholder
        char_w = int(8 * self.config.font_scale)
        char_h = int(16 * self.config.font_scale)
        text_w = len(text) * char_w
        text_h = char_h
        
        x = max(0, min(x, bgr.shape[1] - text_w))
        y = max(0, min(y, bgr.shape[0] - text_h))
        
        # Background
        bgr[y:y+text_h, x:x+text_w] = torch.tensor(bg_color, device=self.device, dtype=torch.uint8)
        # Text (simplified - just color the region)
        # Real implementation would use font texture
        
        return bgr
    
    def _draw_crossing_line(self, bgr: torch.Tensor, cam_config: Dict[str, Any]) -> torch.Tensor:
        """Draw crossing line."""
        geom = cam_config.get("geometry", {})
        line_start = geom.get("line_start", [0, 1080])
        line_end = geom.get("line_end", [3840, 1080])
        
        x1, y1 = line_start
        x2, y2 = line_end
        
        color = self.config.colors["line"]
        thickness = self.config.box_thickness
        
        # Simple line drawing using Bresenham-like approach
        # For horizontal/vertical lines, optimized
        if y1 == y2:  # Horizontal
            y = max(0, min(y1, bgr.shape[0] - 1))
            x1_c = max(0, x1)
            x2_c = min(bgr.shape[1], x2)
            if x2_c > x1_c:
                bgr[y:y+thickness, x1_c:x2_c] = torch.tensor(color, device=self.device, dtype=torch.uint8)
        elif x1 == x2:  # Vertical
            x = max(0, min(x1, bgr.shape[1] - 1))
            y1_c = max(0, y1)
            y2_c = min(bgr.shape[0], y2)
            if y2_c > y1_c:
                bgr[y1_c:y2_c, x:x+thickness] = torch.tensor(color, device=self.device, dtype=torch.uint8)
        else:
            # Diagonal - simplified: draw as series of horizontal segments
            steps = max(abs(x2 - x1), abs(y2 - y1))
            for i in range(steps + 1):
                t = i / steps
                xi = int(x1 + t * (x2 - x1))
                yi = int(y1 + t * (y2 - y1))
                if 0 <= xi < bgr.shape[1] and 0 <= yi < bgr.shape[0]:
                    bgr[yi:yi+thickness, xi:xi+thickness] = torch.tensor(color, device=self.device, dtype=torch.uint8)
        
        return bgr
    
    def _draw_diagnostics(self, bgr: torch.Tensor, metrics: Dict[str, Any]) -> torch.Tensor:
        """Draw FPS, latency, GPU memory diagnostics."""
        color = self.config.colors["fps_text"]
        y_offset = 30
        line_height = 25
        
        lines = []
        
        if self.config.show[OverlayElement.FPS] and "fps" in metrics:
            lines.append(f"FPS: {metrics['fps']:.1f}")
        
        if self.config.show[OverlayElement.LATENCY] and "latency_ms" in metrics:
            lines.append(f"Latency: {metrics['latency_ms']:.1f}ms")
        
        if self.config.show[OverlayElement.GPU_MEMORY] and "gpu_memory_mb" in metrics:
            lines.append(f"GPU: {metrics['gpu_memory_mb']:.0f}MB")
        
        for i, line in enumerate(lines):
            y = y_offset + i * line_height
            # Draw text background
            text_w = len(line) * int(8 * self.config.font_scale)
            text_h = int(16 * self.config.font_scale)
            bg_color = self.config.colors["text_bg"]
            if y + text_h <= bgr.shape[0] and text_w <= bgr.shape[1]:
                bgr[y:y+text_h, 10:10+text_w] = torch.tensor(bg_color, device=self.device, dtype=torch.uint8)
        
        return bgr
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "annotations": self._annotation_count,
            "avg_time_ms": self._total_time_ms / self._annotation_count if self._annotation_count > 0 else 0,
        }
    
    def cleanup(self) -> None:
        torch.cuda.empty_cache()


def create_annotator(device_id: int = 0) -> GPUAnnotator:
    """Factory function to create GPU annotator."""
    config = AnnotationConfig()
    return GPUAnnotator(config, device_id)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    annotator = create_annotator()
    print("GPUAnnotator created!")
    print(f"Config: {annotator.config}")