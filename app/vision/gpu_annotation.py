"""
Phase R3.14-H.9.5 — GPU Annotation Renderer.

GPU-resident annotation for 4K master frame. Eliminates full-frame 4K
GPU->CPU->GPU round trip from the authoritative video-output path.

Architecture:
    4K CUDA surface (authoritative master)
        │
        ├── GPU rectangle/line drawing via PyTorch tensor indexing
        ├── GPU text: CPU PIL rasterization -> small mat upload -> alpha blend
        └── Result: 4K CUDA annotated surface -> direct NVENC (hwupload_cuda)

Per-camera isolation: each camera_id has its own annotation surface.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class GPUAnnotationConfig:
    """Configuration for GPU annotation."""
    enabled: bool = False
    gpu_device: int = 0
    # Text rendering (CPU PIL -> GPU upload)
    text_enabled: bool = True
    text_font_path: str = "C:/Windows/Fonts/arial.ttf"
    text_font_size: int = 48
    text_color: Tuple[int, int, int] = (0, 255, 0)  # BGR
    text_bg_color: Tuple[int, int, int] = (0, 0, 0)
    # Geometry
    rect_thickness: int = 3
    line_thickness: int = 3
    # Colors (BGR)
    color_known: Tuple[int, int, int] = (255, 255, 0)      # cyan
    color_ambiguous: Tuple[int, int, int] = (0, 165, 255)  # amber
    color_unknown: Tuple[int, int, int] = (0, 255, 0)      # green
    color_crossing_line: Tuple[int, int, int] = (0, 255, 0)
    color_region: Tuple[int, int, int] = (255, 255, 0)
    color_camera_tag: Tuple[int, int, int] = (255, 255, 255)
    color_camera_tag_bg: Tuple[int, int, int] = (0, 0, 0)
    # Fallback
    cpu_fallback: bool = True
    gpu_annotation_cpu_fallback: bool = True  # Alias for publisher access


@dataclass
class GPUAnnotationMetrics:
    """Metrics for GPU annotation operations."""
    frames_annotated: int = 0
    gpu_rect_draws: int = 0
    gpu_line_draws: int = 0
    gpu_text_uploads: int = 0
    gpu_region_draws: int = 0
    cpu_fallback_count: int = 0
    total_time_ms: float = 0.0
    gpu_time_ms: float = 0.0
    cpu_text_time_ms: float = 0.0
    upload_time_ms: float = 0.0
    errors: int = 0


def _clamp_bbox(
    bbox: Sequence[float],
    width: int,
    height: int,
) -> Optional[Tuple[int, int, int, int]]:
    """Clamp a (x1, y1, x2, y2) bbox to the frame interior. Returns None if empty."""
    if not bbox or len(bbox) < 4:
        return None
    x1 = int(max(0, min(width - 1, round(float(bbox[0])))))
    y1 = int(max(0, min(height - 1, round(float(bbox[1])))))
    x2 = int(max(0, min(width - 1, round(float(bbox[2])))))
    y2 = int(max(0, min(height - 1, round(float(bbox[3])))))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _font_scale_for_frame(height: int) -> float:
    """Pick a font scale proportional to the frame height."""
    if height <= 0:
        return 0.5
    return max(0.4, min(2.0, height / 1080.0))


def _line_thickness_for_frame(height: int) -> int:
    if height <= 0:
        return 2
    return max(2, min(5, height // 540))


class GPUAnnotationRenderer:
    """
    GPU-resident annotation renderer for 4K master frame.
    
    Uses PyTorch CUDA tensors for geometry (rectangles, lines, polygons)
    and PIL CPU rasterization + small GPU upload for text overlays.
    
    Per-camera isolation: one renderer per camera_id with its own surface.
    """

    __slots__ = ("config", "metrics", "_surface", "_surface_shape", "_lock", "_pil_font", "_initialized")

    def __init__(self, config: Optional[GPUAnnotationConfig] = None):
        self.config = config or GPUAnnotationConfig()
        self.metrics = GPUAnnotationMetrics()
        self._surface = None
        self._surface_shape = None
        self._lock = threading.Lock()
        self._pil_font = None
        self._initialized = False
        
        if self.config.enabled:
            self._init_gpu()

    def _init_gpu(self) -> None:
        """Initialize GPU resources."""
        try:
            import torch
            if not torch.cuda.is_available():
                logger.warning("GPUAnnotationRenderer: CUDA not available, disabling GPU annotation")
                self.config.enabled = False
                return
            
            # Pre-load PIL font
            if self.config.text_enabled:
                try:
                    from PIL import ImageFont
                    self._pil_font = ImageFont.truetype(self.config.text_font_path, self.config.text_font_size)
                except Exception as e:
                    logger.warning(f"GPUAnnotationRenderer: failed to load font {self.config.text_font_path}: {e}")
                    self._pil_font = None
            
            self._initialized = True
            logger.info("GPUAnnotationRenderer: GPU annotation enabled")
        except ImportError:
            logger.warning("GPUAnnotationRenderer: torch not available, disabling GPU annotation")
            self.config.enabled = False

    def _ensure_surface(self, shape: Tuple[int, int, int]) -> "torch.Tensor":
        """Get or allocate the annotation surface for the given shape."""
        import torch
        
        with self._lock:
            if self._surface is not None and self._surface_shape == shape:
                return self._surface
            
            h, w, c = shape
            if c != 3:
                raise ValueError(f"Expected 3 channels, got {c}")
            
            # Allocate new surface on GPU
            self._surface = torch.empty((h, w, 3), dtype=torch.uint8, device=f"cuda:{self.config.gpu_device}")
            self._surface_shape = shape
            logger.info(f"GPUAnnotationRenderer: allocated annotation surface {shape} (~{h*w*3/1024/1024:.1f} MiB)")
            return self._surface

    def annotate_gpu(
        self,
        gpu_surface: "torch.Tensor",  # 4K master surface (H, W, 3) uint8 on CUDA
        detections: Optional[List[Dict[str, Any]]] = None,
        lines: Optional[List[Dict[str, Any]]] = None,
        regions: Optional[List[Dict[str, Any]]] = None,
        camera_id: Optional[str] = None,
    ) -> "torch.Tensor":
        """
        Annotate the GPU surface in-place and return the annotated surface.
        
        The input gpu_surface is the authoritative 4K master frame. We draw
        directly on it (or on a copy if caller wants to preserve original).
        
        Returns the same gpu_surface tensor (modified in-place).
        """
        if not self.config.enabled or not self._initialized:
            self.metrics.cpu_fallback_count += 1
            return gpu_surface
        
        import torch
        
        t0 = time.perf_counter()
        
        try:
            h, w = gpu_surface.shape[:2]
            font_scale = _font_scale_for_frame(h)
            thickness = self.config.rect_thickness
            line_thickness = self.config.line_thickness
            text_thickness = max(1, thickness - 1)
            
            # Draw regions (filled polygons with alpha)
            if regions:
                self._draw_regions_gpu(gpu_surface, regions)
                self.metrics.gpu_region_draws += 1
            
            # Draw lines (crossing line)
            if lines:
                self._draw_lines_gpu(gpu_surface, lines)
                self.metrics.gpu_line_draws += len(lines)
            
            # Draw detection rectangles + labels
            if detections:
                self._draw_detections_gpu(
                    gpu_surface, detections,
                    font_scale, thickness, text_thickness
                )
                self.metrics.gpu_rect_draws += len(detections)
            
            # Draw camera tag
            if camera_id:
                self._draw_camera_tag_gpu(gpu_surface, camera_id, font_scale, text_thickness)
            
            self.metrics.frames_annotated += 1
            self.metrics.total_time_ms += (time.perf_counter() - t0) * 1000
            
            return gpu_surface
            
        except Exception as e:
            logger.error(f"GPUAnnotationRenderer: GPU annotation failed: {e}")
            self.metrics.errors += 1
            if self.config.cpu_fallback:
                self.metrics.cpu_fallback_count += 1
            return gpu_surface

    def _draw_detections_gpu(
        self,
        canvas: "torch.Tensor",
        detections: List[Dict[str, Any]],
        font_scale: float,
        thickness: int,
        text_thickness: int,
    ) -> None:
        """Draw detection rectangles and labels on GPU surface."""
        import torch
        
        height, width = canvas.shape[:2]
        
        for det in detections:
            bbox = det.get("bbox") if isinstance(det, dict) else None
            if not bbox:
                continue
            clamped = _clamp_bbox(bbox, width, height)
            if clamped is None:
                continue
            x1, y1, x2, y2 = clamped

            identity_certainty = (det.get("identity_certainty") or "unknown") if isinstance(det, dict) else "unknown"
            if identity_certainty == "known":
                color = self.config.color_known
            elif identity_certainty in ("ambiguous", "insufficient"):
                color = self.config.color_ambiguous
            else:
                color = self.config.color_unknown

            # Draw rectangle on GPU via tensor indexing
            # Top edge
            canvas[y1:y1+thickness, x1:x2, :] = torch.tensor(color, dtype=torch.uint8, device=canvas.device)
            # Bottom edge
            canvas[y2-thickness:y2, x1:x2, :] = torch.tensor(color, dtype=torch.uint8, device=canvas.device)
            # Left edge
            canvas[y1:y2, x1:x1+thickness, :] = torch.tensor(color, dtype=torch.uint8, device=canvas.device)
            # Right edge
            canvas[y1:y2, x2-thickness:x2, :] = torch.tensor(color, dtype=torch.uint8, device=canvas.device)

            # Text label (CPU PIL -> GPU upload -> alpha blend)
            label = det.get("label") or det.get("track_id") or "Person"
            if isinstance(det.get("person_id"), str) and det.get("person_id"):
                label = det["person_id"]
            confidence = det.get("confidence")
            if isinstance(confidence, (int, float)) and confidence > 0:
                text = f"{label} {int(round(float(confidence) * 100))}%"
            else:
                text = str(label)

            if self.config.text_enabled and self._pil_font:
                self._draw_text_gpu(canvas, text, x1, y1, color, font_scale, text_thickness)

    def _draw_lines_gpu(
        self,
        canvas: "torch.Tensor",
        lines: List[Dict[str, Any]],
    ) -> None:
        """Draw lines on GPU surface using Bresenham-like tensor ops."""
        import torch
        
        height, width = canvas.shape[:2]
        color = self.config.color_crossing_line
        color_tensor = torch.tensor(color, dtype=torch.uint8, device=canvas.device)
        
        for line in lines:
            if not isinstance(line, dict):
                continue
            if line.get("enabled") is False:
                continue
            start = line.get("start") or {}
            end = line.get("end") or {}
            if not (isinstance(start, dict) and isinstance(end, dict)):
                continue
            try:
                x1 = int(max(0, min(width - 1, round(float(start.get("x", 0))))))
                y1 = int(max(0, min(height - 1, round(float(start.get("y", 0))))))
                x2 = int(max(0, min(width - 1, round(float(end.get("x", 0))))))
                y2 = int(max(0, min(height - 1, round(float(end.get("y", 0))))))
            except (TypeError, ValueError):
                continue
            
            # Simple GPU line drawing using interpolation
            # For thick lines, we draw multiple parallel 1-pixel lines
            line_thickness = self.config.line_thickness
            
            # Calculate line points using integer Bresenham (CPU) then upload
            # For performance, we use a simple linear interpolation on GPU
            steps = max(abs(x2 - x1), abs(y2 - y1), 1)
            if steps <= 1:
                continue
            
            # Generate line coordinates on CPU (cheap for thin lines)
            xs = torch.linspace(x1, x2, steps, dtype=torch.long, device=canvas.device)
            ys = torch.linspace(y1, y2, steps, dtype=torch.long, device=canvas.device)
            
            # Draw thick line by offsetting
            for dy in range(-line_thickness//2, line_thickness//2 + 1):
                for dx in range(-line_thickness//2, line_thickness//2 + 1):
                    y_coords = (ys + dy).clamp(0, height - 1)
                    x_coords = (xs + dx).clamp(0, width - 1)
                    canvas[y_coords, x_coords, :] = color_tensor

    def _draw_regions_gpu(
        self,
        canvas: "torch.Tensor",
        regions: List[Dict[str, Any]],
    ) -> None:
        """Draw filled polygons (regions) on GPU surface with alpha blend."""
        import torch
        
        height, width = canvas.shape[:2]
        color = self.config.color_region
        color_tensor = torch.tensor(color, dtype=torch.uint8, device=canvas.device)
        
        for region in regions:
            if not isinstance(region, dict):
                continue
            if region.get("enabled") is False:
                continue
            vertices = region.get("vertices")
            if not vertices:
                continue
            pts = []
            for v in vertices:
                if not isinstance(v, dict):
                    continue
                try:
                    x = int(max(0, min(width - 1, round(float(v.get("x", 0))))))
                    y = int(max(0, min(height - 1, round(float(v.get("y", 0))))))
                except (TypeError, ValueError):
                    continue
                pts.append((x, y))
            if len(pts) < 3:
                continue
            
            # For polygon fill on GPU, we use a simple scanline approach
            # Create a mask tensor and use it for alpha blending
            # This is a simplified version - production would use a proper polygon fill kernel
            mask = torch.zeros((height, width), dtype=torch.bool, device=canvas.device)
            
            # Simple approach: draw polygon edges and fill (CPU-assisted for now)
            # For true GPU fill, we'd need a custom CUDA kernel or use NPP
            # Here we fall back to a simpler approach: draw bounding box approximation
            # or use existing PyTorch operations
            ys = [p[1] for p in pts]
            xs = [p[0] for p in pts]
            min_y, max_y = min(ys), max(ys)
            min_x, max_x = min(xs), max(xs)
            
            # For the crossing line regions, use a simple alpha overlay on the region bounding box
            # with reduced opacity (this is an approximation for now)
            if max_y > min_y and max_x > min_x:
                alpha = 0.15
                roi = canvas[min_y:max_y, min_x:max_x].float()
                color_float = color_tensor.float().view(1, 1, 3) / 255.0
                roi = roi * (1 - alpha) + color_float * 255 * alpha
                canvas[min_y:max_y, min_x:max_x] = roi.clamp(0, 255).to(torch.uint8)

    def _draw_camera_tag_gpu(
        self,
        canvas: "torch.Tensor",
        camera_id: str,
        font_scale: float,
        text_thickness: int,
    ) -> None:
        """Draw camera tag on GPU surface."""
        if not self.config.text_enabled or not self._pil_font:
            return
        
        import torch
        from PIL import Image, ImageDraw
        
        height, width = canvas.shape[:2]
        text = f"{camera_id}  AI"
        
        # Position: bottom right
        margin = 12
        # Estimate text size
        dummy_img = Image.new('RGB', (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)
        bbox = dummy_draw.textbbox((0, 0), text, font=self._pil_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        
        x2 = width - margin
        y2 = height - margin
        x1 = x2 - tw - 12
        y1 = y2 - th - 8
        
        # Draw background rectangle on GPU
        bg_color = torch.tensor(self.config.color_camera_tag_bg, dtype=torch.uint8, device=canvas.device)
        canvas[y1:y2, x1:x2, :] = bg_color
        
        # Draw text via CPU->GPU upload
        self._draw_text_gpu(canvas, text, x1 + 6, y1, self.config.color_camera_tag, font_scale, text_thickness)

    def _draw_text_gpu(
        self,
        canvas: "torch.Tensor",
        text: str,
        x: int,
        y: int,
        color: Tuple[int, int, int],
        font_scale: float,
        text_thickness: int,
    ) -> None:
        """Draw text by CPU PIL rasterization -> GPU upload -> alpha blend."""
        import torch
        from PIL import Image, ImageDraw
        
        t0 = time.perf_counter()
        
        height, width = canvas.shape[:2]
        
        # Create text image on CPU
        # Estimate size (use textbbox for newer Pillow versions)
        dummy_img = Image.new('RGBA', (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)
        bbox = dummy_draw.textbbox((0, 0), text, font=self._pil_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        
        # Add padding
        pad = 4
        img_w = tw + pad * 2
        img_h = th + pad * 2
        
        # Render text on CPU
        img = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Background
        bg_color = self.config.text_bg_color
        draw.rectangle([0, 0, img_w - 1, img_h - 1], fill=(bg_color[2], bg_color[1], bg_color[0], 200))  # BGR->RGB
        # Text
        text_color_rgb = (color[2], color[1], color[0], 255)  # BGR->RGB
        draw.text((pad, pad), text, fill=text_color_rgb, font=self._pil_font)
        
        # Convert to numpy and upload to GPU
        arr = np.array(img, dtype=np.uint8)  # (H, W, 4) RGBA
        self.metrics.cpu_text_time_ms += (time.perf_counter() - t0) * 1000
        
        t1 = time.perf_counter()
        
        # Upload to GPU
        text_gpu = torch.from_numpy(arr).to(device=canvas.device, non_blocking=True)
        # text_gpu is (H, W, 4) RGBA
        
        # Alpha blend onto canvas
        # Calculate destination region
        dst_y1 = max(0, min(height - 1, y))
        dst_x1 = max(0, min(width - 1, x))
        dst_y2 = min(height, dst_y1 + img_h)
        dst_x2 = min(width, dst_x1 + img_w)
        
        src_h = dst_y2 - dst_y1
        src_w = dst_x2 - dst_x1
        
        if src_h > 0 and src_w > 0:
            # Crop source if needed
            src = text_gpu[:src_h, :src_w]
            
            # Alpha blend: dst = dst * (1 - alpha) + src_rgb * alpha
            alpha = src[:, :, 3:4].float() / 255.0  # (H, W, 1)
            src_rgb = src[:, :, :3].float()  # (H, W, 3)
            dst_roi = canvas[dst_y1:dst_y2, dst_x1:dst_x2].float()
            
            blended = dst_roi * (1 - alpha) + src_rgb * alpha
            canvas[dst_y1:dst_y2, dst_x1:dst_x2] = blended.clamp(0, 255).to(torch.uint8)
        
        self.metrics.upload_time_ms += (time.perf_counter() - t1) * 1000
        self.metrics.gpu_text_uploads += 1

    def get_metrics(self) -> Dict[str, Any]:
        """Get renderer metrics."""
        m = self.metrics
        return {
            "enabled": self.config.enabled,
            "frames_annotated": m.frames_annotated,
            "gpu_rect_draws": m.gpu_rect_draws,
            "gpu_line_draws": m.gpu_line_draws,
            "gpu_text_uploads": m.gpu_text_uploads,
            "gpu_region_draws": m.gpu_region_draws,
            "cpu_fallback_count": m.cpu_fallback_count,
            "avg_total_time_ms": m.total_time_ms / m.frames_annotated if m.frames_annotated > 0 else 0.0,
            "avg_gpu_time_ms": m.gpu_time_ms / m.frames_annotated if m.frames_annotated > 0 else 0.0,
            "avg_cpu_text_time_ms": m.cpu_text_time_ms / m.frames_annotated if m.frames_annotated > 0 else 0.0,
            "avg_upload_time_ms": m.upload_time_ms / m.gpu_text_uploads if m.gpu_text_uploads > 0 else 0.0,
            "errors": m.errors,
        }

    def reset(self) -> None:
        """Reset metrics."""
        self.metrics = GPUAnnotationMetrics()
        with self._lock:
            self._surface = None
            self._surface_shape = None


# Process-singleton pool
_RENDERERS: Dict[str, GPUAnnotationRenderer] = {}
_RENDERERS_LOCK = threading.Lock()


def get_gpu_annotation_renderer(camera_id: str, config: Optional[GPUAnnotationConfig] = None) -> GPUAnnotationRenderer:
    """Get or create the per-camera GPU annotation renderer."""
    global _RENDERERS
    with _RENDERERS_LOCK:
        if camera_id not in _RENDERERS:
            _RENDERERS[camera_id] = GPUAnnotationRenderer(config)
        return _RENDERERS[camera_id]


def reset_gpu_annotation_renderers() -> None:
    """Reset all renderers (for tests)."""
    global _RENDERERS
    with _RENDERERS_LOCK:
        for renderer in _RENDERERS.values():
            renderer.reset()
        _RENDERERS.clear()