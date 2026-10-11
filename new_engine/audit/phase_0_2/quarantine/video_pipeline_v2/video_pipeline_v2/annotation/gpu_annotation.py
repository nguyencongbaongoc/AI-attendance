"""
GPU Annotation - V2 GPU-first video pipeline.

Annotates GPU frames with detection results, bounding boxes, labels, lines.
All annotation happens on GPU tensors - no CPU OpenCV rendering.
Produces annotated BGR GPUFrame for NVENC encoder.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any, Union

import torch

from video_pipeline_v2.core.gpu_frame import GPUFrame, nv12_to_bgr_cuda, bgr_to_nv12_cuda
from video_pipeline_v2.ai.scrfd_detector import FaceDetection
from video_pipeline_v2.ai.yolo_detector import PersonDetection
from video_pipeline_v2.ai.tracking import Track

logger = logging.getLogger(__name__)


@dataclass
class AnnotationConfig:
    """Configuration for GPU annotation."""
    # Colors (BGR format for OpenCV compatibility, but we'll use RGB in GPU tensors)
    bbox_color: Tuple[int, int, int] = (0, 255, 0)  # Green in BGR = (0, 255, 0) -> RGB (0, 255, 0)
    text_color: Tuple[int, int, int] = (255, 255, 255)  # White
    line_color: Tuple[int, int, int] = (0, 0, 255)  # Red
    # Line thickness
    bbox_thickness: int = 2
    text_thickness: int = 1
    # Font
    font_scale: float = 0.6
    # Show info
    show_confidence: bool = True
    show_track_id: bool = True
    show_class_name: bool = True
    # Crosshair line
    show_crossing_line: bool = True
    crossing_line_color: Tuple[int, int, int] = (255, 0, 0)  # Blue


class GPUAnnotationRenderer:
    """
    GPU annotation renderer.
    
    Takes GPUFrame (NV12) and annotations, produces annotated BGR GPUFrame.
    All drawing operations happen on CUDA tensors using PyTorch.
    """
    
    def __init__(self, config: Optional[AnnotationConfig] = None, device_id: int = 0):
        self.config = config or AnnotationConfig()
        self.device_id = device_id
        self.device_str = f'cuda:{device_id}'
    
    def annotate_frame(
        self,
        frame: GPUFrame,
        face_detections: List[FaceDetection] = None,
        person_detections: List[PersonDetection] = None,
        tracks: List[Track] = None,
        crossing_points: List[Tuple[float, float]] = None,
        text_overlays: List[Tuple[str, Tuple[float, float]]] = None,
    ) -> GPUFrame:
        """
        Annotate a GPUFrame with detection results.
        
        Pipeline:
            GPUFrame (NV12) 
                → Convert to BGR (GPU)
                → Draw bboxes, labels, lines (GPU)
                → Create annotated GPUFrame (BGR)
        
        Returns:
            New GPUFrame with annotation tensor set (BGR format on GPU)
        """
        if face_detections is None:
            face_detections = []
        if person_detections is None:
            person_detections = []
        if tracks is None:
            tracks = []
        if crossing_points is None:
            crossing_points = []
        if text_overlays is None:
            text_overlays = []
        
        # Convert NV12 to BGR for annotation
        y_tensor, uv_tensor = frame.get_tensors()
        
        # Create annotation tensor (BGR)
        annotated_bgr = nv12_to_bgr_cuda(y_tensor, uv_tensor, limited_range=True)
        
        # Draw face detections
        for det in face_detections:
            annotated_bgr = self._draw_bbox(
                annotated_bgr, det.bbox, 
                color=self.config.bbox_color,
                thickness=self.config.bbox_thickness,
                label=f"Face {det.confidence:.2f}"
            )
        
        # Draw person detections
        for det in person_detections:
            annotated_bgr = self._draw_bbox(
                annotated_bgr, det.bbox,
                color=(255, 165, 0),  # Orange in BGR
                thickness=self.config.bbox_thickness,
                label=f"Person {det.confidence:.2f}"
            )
        
        # Draw tracks
        for track in tracks:
            # Different colors for different lifecycle states
            if track.is_new:
                color = (0, 165, 255)  # Orange-red
            elif track.is_active:
                color = (0, 255, 0)  # Green
            elif track.is_lost:
                color = (0, 165, 255)  # Yellow-orange
            else:
                color = (128, 128, 128)  # Gray
            
            annotated_bgr = self._draw_bbox(
                annotated_bgr, track.bbox_original_frame,
                color=color,
                thickness=2,
                label=f"ID:{track.track_id}" if self.config.show_track_id else None
            )
            
            # Draw center point
            cx, cy = track.center
            annotated_bgr = self._draw_circle(
                annotated_bgr, (int(cx), int(cy)), 
                color=color, radius=4
            )
        
        # Draw crossing line
        if self.config.show_crossing_line and crossing_points:
            for pt in crossing_points:
                annotated_bgr = self._draw_cross(
                    annotated_bgr, (int(pt[0]), int(pt[1])),
                    color=self.config.crossing_line_color,
                    size=20
                )
        
        # Draw text overlays
        for text, pos in text_overlays:
            annotated_bgr = self._draw_text(
                annotated_bgr, text, (int(pos[0]), int(pos[1])),
                color=self.config.text_color
            )
        
        # Create annotated GPUFrame
        annotated_frame = GPUFrame(
            camera_id=frame.camera_id,
            frame_id=frame.frame_id,
            timestamp=frame.timestamp,
            pts=frame.pts,
            dts=frame.dts,
            width=frame.width,
            height=frame.height,
            actual_width=frame.actual_width,
            actual_height=frame.actual_height,
            pixel_format=frame.pixel_format,
            cuda_context=frame.cuda_context,
        )
        
        # Set the annotation tensor (BGR)
        # Note: The frame still has NV12 tensors; the annotation is a separate overlay
        annotated_frame.set_annotation_tensor(annotated_bgr)
        
        # Copy other fields from original frame
        annotated_frame.y_tensor = frame.y_tensor.clone() if frame.y_tensor is not None else None
        annotated_frame.uv_tensor = frame.uv_tensor.clone() if frame.uv_tensor is not None else None
        
        return annotated_frame
    
    def _draw_bbox(
        self,
        image: torch.Tensor,
        bbox: Tuple[float, float, float, float],
        color: Tuple[int, int, int],
        thickness: int = 2,
        label: Optional[str] = None,
    ) -> torch.Tensor:
        """Draw bounding box on BGR image tensor."""
        H, W = image.shape[:2]
        x1, y1, x2, y2 = bbox
        
        # Clamp to image
        x1 = max(0, min(int(x1), W - 1))
        y1 = max(0, min(int(y1), H - 1))
        x2 = max(0, min(int(x2), W - 1))
        y2 = max(0, min(int(y2), H - 1))
        
        # Draw rectangle lines (simplified - draw top, bottom, left, right)
        # Top line
        for t in range(min(thickness, 10)):
            y_line = y1 + t if y1 + t < H else y1
            if y_line < H:
                image[y_line, max(0, x1):min(W, x2), :] = torch.tensor(color, device=image.device, dtype=torch.uint8)
        
        # Bottom line
        for t in range(min(thickness, 10)):
            y_line = y2 - t if y2 - t >= 0 else y2
            if y_line >= 0:
                image[y_line, max(0, x1):min(W, x2), :] = torch.tensor(color, device=image.device, dtype=torch.uint8)
        
        # Left line
        for t in range(min(thickness, 10)):
            x_line = x1 + t if x1 + t < W else x1
            if x_line < W:
                image[max(0, y1):min(H, y2), x_line, :] = torch.tensor(color, device=image.device, dtype=torch.uint8)
        
        # Right line
        for t in range(min(thickness, 10)):
            x_line = x2 - t if x2 - t >= 0 else x2
            if x_line >= 0:
                image[max(0, y1):min(H, y2), x_line, :] = torch.tensor(color, device=image.device, dtype=torch.uint8)
        
        # Draw label
        if label:
            image = self._draw_text(image, label, (x1, max(0, y1 - 5)))
        
        return image
    
    def _draw_text(
        self,
        image: torch.Tensor,
        text: str,
        position: Tuple[int, int],
        color: Tuple[int, int, int] = (255, 255, 255),
        font_scale: float = 0.6,
    ) -> torch.Tensor:
        """Draw text on image. Simplified - draws basic text representation."""
        # Note: Full text rendering on GPU is complex.
        # For V2, we use a simplified approach or rely on NVENC overlay.
        # This is a basic placeholder.
        x, y = position
        H, W = image.shape[:2]
        
        # Draw a text background box
        box_w = max(50, len(text) * 10)
        box_h = 20
        y_start = max(0, y - box_h)
        x_start = max(0, x)
        
        # Simple text representation - just draw a colored rectangle as indicator
        # In production, this would use a proper GPU text renderer
        image[max(0, y_start):min(H, y_start + box_h), x_start:min(W, x_start + box_w), :] = \
            torch.tensor([30, 30, 60], device=image.device, dtype=torch.uint8)
        
        return image
    
    def _draw_circle(
        self,
        image: torch.Tensor,
        center: Tuple[int, int],
        color: Tuple[int, int, int],
        radius: int = 4,
    ) -> torch.Tensor:
        """Draw a circle on the BGR image."""
        cx, cy = center
        H, W = image.shape[:2]
        
        # Simple circle drawing using distance
        for y in range(max(0, cy - radius), min(H, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(W, cx + radius + 1)):
                dist_sq = (x - cx) ** 2 + (y - cy) ** 2
                if dist_sq <= radius ** 2:
                    image[y, x, :] = torch.tensor(color, device=image.device, dtype=torch.uint8)
        
        return image
    
    def _draw_cross(
        self,
        image: torch.Tensor,
        center: Tuple[int, int],
        color: Tuple[int, int, int],
        size: int = 20,
    ) -> torch.Tensor:
        """Draw a cross (+) at center point."""
        cx, cy = center
        H, W = image.shape[:2]
        
        half = size // 2
        
        # Horizontal line
        y_line = cy
        x_start = max(0, cx - half)
        x_end = min(W, cx + half)
        if 0 <= y_line < H:
            image[y_line, x_start:x_end, :] = torch.tensor(color, device=image.device, dtype=torch.uint8)
        
        # Vertical line
        x_line = cx
        y_start = max(0, cy - half)
        y_end = min(H, cy + half)
        if 0 <= x_line < W:
            image[y_start:y_end, x_line, :] = torch.tensor(color, device=image.device, dtype=torch.uint8)
        
        return image
    
    def annotate_for_encoder(
        self,
        frame: GPUFrame,
        annotations: Optional[List[Dict]] = None,
    ) -> GPUFrame:
        """
        Create annotated frame for NVENC encoder.
        Returns GPUFrame with annotation tensor set.
        """
        annotated = self.annotate_frame(frame)
        return annotated
    
    def get_annotation_tensor(self, frame: GPUFrame) -> Optional[torch.Tensor]:
        """Get the annotation overlay tensor from a frame."""
        return frame.get_annotation_tensor()
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        pass


def create_annotation_renderer(
    bbox_color: Tuple[int, int, int] = (0, 255, 0),
    show_confidence: bool = True,
    show_track_id: bool = True,
    device_id: int = 0,
) -> GPUAnnotationRenderer:
    """Factory function to create GPU annotation renderer."""
    config = AnnotationConfig(
        bbox_color=bbox_color,
        show_confidence=show_confidence,
        show_track_id=show_track_id,
    )
    return GPUAnnotationRenderer(config, device_id)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    print("GPU Annotation renderer loaded!")
    print(f"Annotation config: bbox_color={AnnotationConfig().bbox_color}")