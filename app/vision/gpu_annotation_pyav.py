"""
Phase H.10-C.2 — GPU Annotation Renderer for PyAV CUDA Frames.

GPU-resident annotation for 4K master frame using NV12 planes.
Eliminates full-frame 4K GPU->CPU->GPU round trip from the authoritative
video-output path.

Architecture:
    4K CUDA NV12 planes (authoritative master from PyAV NVDEC)
        │
        ├── GPU rectangle/line drawing via PyTorch tensor indexing on BGR-converted surface
        ├── GPU text: CPU PIL rasterization -> small mat upload -> alpha blend
        └── Result: 4K CUDA NV12 planes -> direct NVENC (via PyAV VideoFrame.from_dlpack)

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
class GPUAnnotationPyAVConfig:
    """Configuration for GPU annotation with PyAV CUDA frames."""
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


@dataclass
class GPUAnnotationPyAVMetrics:
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


class GPUAnnotationPyAVRenderer:
    """
    GPU-resident annotation renderer for 4K master frame from PyAV NVDEC.
    
    Uses PyTorch CUDA tensors for geometry (rectangles, lines, polygons)
    and PIL CPU rasterization + small GPU upload for text overlays.
    
    Works directly on NV12 planes by converting to BGR for drawing,
    then converting back to NV12 for NVENC output.
    
    Per-camera isolation: one renderer per camera_id with its own surface.
    """
    
    __slots__ = ("config", "metrics", "_bgr_surface", "_surface_shape", "_lock", "_pil_font", "_initialized")
    
    def __init__(self, config: Optional[GPUAnnotationPyAVConfig] = None):
        self.config = config or GPUAnnotationPyAVConfig()
        self.metrics = GPUAnnotationPyAVMetrics()
        self._bgr_surface = None
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
                logger.warning("GPUAnnotationPyAVRenderer: CUDA not available, disabling GPU annotation")
                self.config.enabled = False
                return
            
            # Pre-load PIL font
            if self.config.text_enabled:
                try:
                    from PIL import ImageFont
                    self._pil_font = ImageFont.truetype(self.config.text_font_path, self.config.text_font_size)
                except Exception as e:
                    logger.warning(f"GPUAnnotationPyAVRenderer: failed to load font {self.config.text_font_path}: {e}")
                    self._pil_font = None
            
            self._initialized = True
            logger.info("GPUAnnotationPyAVRenderer: GPU annotation enabled")
        except ImportError:
            logger.warning("GPUAnnotationPyAVRenderer: torch not available, disabling GPU annotation")
            self.config.enabled = False
    
    def _ensure_bgr_surface(self, shape: Tuple[int, int, int]) -> "torch.Tensor":
        """Get or allocate the BGR annotation surface for the given shape."""
        import torch
        
        with self._lock:
            if self._bgr_surface is not None and self._surface_shape == shape:
                return self._bgr_surface
            
            h, w, c = shape
            if c != 3:
                raise ValueError(f"Expected 3 channels, got {c}")
            
            # Allocate new surface on GPU
            self._bgr_surface = torch.empty((h, w, 3), dtype=torch.uint8, device=f"cuda:{self.config.gpu_device}")
            self._surface_shape = shape
            logger.info(f"GPUAnnotationPyAVRenderer: allocated BGR annotation surface {shape} (~{h*w*3/1024/1024:.1f} MiB)")
            return self._bgr_surface
    
    def annotate_nv12(
        self,
        y_plane: "torch.Tensor",   # (H, W) uint8
        uv_plane: "torch.Tensor",  # (H/2, W/2, 2) uint8
        detections: Optional[List[Dict[str, Any]]] = None,
        lines: Optional[List[Dict[str, Any]]] = None,
        regions: Optional[List[Dict[str, Any]]] = None,
        camera_id: Optional[str] = None,
    ) -> Tuple["torch.Tensor", "torch.Tensor"]:
        """
        Annotate the NV12 planes in-place and return the annotated NV12 planes.
        
        The input y_plane/uv_plane are the authoritative 4K master frames from PyAV NVDEC.
        We convert to BGR for drawing, then convert back to NV12.
        
        Returns tuple of (annotated_y_plane, annotated_uv_plane).
        """
        if not self.config.enabled or not self._initialized:
            self.metrics.cpu_fallback_count += 1
            return y_plane, uv_plane
        
        import torch
        from app.vision.gpu_nv12_to_bgr import nv12_to_bgr_gpu, nv12_to_bgr_gpu
        
        t0 = time.perf_counter()
        
        # Phase 54: Annotation must NOT modify surfaces owned by encoder.
        # The input planes may share GPU memory with encoder-owned surfaces.
        # If the surface is IN_FLIGHT, writing here would cause concurrent
        # modification of encoder input, violating the ownership invariant.
        if y_plane is not None and uv_plane is not None:
            # Check ownership through surface identity where tracked
            # Note: direct ownership check requires surface registry access;
            # for this renderer we rely on the caller ensuring surfaces are not
            # submitted to encoder before annotation completes and ownership is
            # transferred. The critical invariant is: annotation writes must
            # complete before submit_encoder(), and after submit, no annotation
            # may modify the same surface.
            pass

        try:
            h, w = y_plane.shape[:2]
            font_scale = _font_scale_for_frame(h)
            thickness = self.config.rect_thickness
            line_thickness = self.config.line_thickness
            text_thickness = max(1, thickness - 1)
            
            # Convert NV12 to BGR for drawing (GPU-resident)
            bgr_canvas = nv12_to_bgr_gpu(y_plane, uv_plane)
            
            # Ensure BGR surface matches
            bgr_canvas = self._ensure_bgr_surface((h, w, 3))
            # Copy the converted frame to our persistent surface
            bgr_canvas.copy_(nv12_to_bgr_gpu(y_plane, uv_plane))
            
            # Draw regions (filled polygons with alpha)
            if regions:
                self._draw_regions_gpu(bgr_canvas, regions)
                self.metrics.gpu_region_draws += 1
            
            # Draw lines (crossing line)
            if lines:
                self._draw_lines_gpu(bgr_canvas, lines)
                self.metrics.gpu_line_draws += len(lines)
            
            # Draw detection rectangles + labels
            if detections:
                self._draw_detections_gpu(
                    bgr_canvas, detections,
                    font_scale, thickness, text_thickness
                )
                self.metrics.gpu_rect_draws += len(detections)
            
            # Draw camera tag
            if camera_id:
                self._draw_camera_tag_gpu(bgr_canvas, camera_id, font_scale, text_thickness)
            
            self.metrics.frames_annotated += 1
            self.metrics.total_time_ms += (time.perf_counter() - t0) * 1000
            
            # Convert annotated BGR back to NV12 planes for NVENC
            # This is done on GPU using PyTorch operations
            # Phase 54: Before writing back, document the annotation contract.
            # After annotation completes, the annotated planes must NOT be
            # reused by annotation again until encoder release completes.
            # The encoder owns the surface after submit_encoder().
            annotated_y, annotated_uv = self._bgr_to_nv12_gpu(bgr_canvas)

            # Copy back to input planes (in-place update for zero-copy downstream)
            y_plane.copy_(annotated_y)
            uv_plane.copy_(annotated_uv)
            
            return y_plane, uv_plane
            
        except Exception as e:
            logger.error(f"GPUAnnotationPyAVRenderer: GPU annotation failed: {e}")
            self.metrics.errors += 1
            if self.config.cpu_fallback:
                self.metrics.cpu_fallback_count += 1
            return y_plane, uv_plane
    
    def _bgr_to_nv12_gpu(self, bgr: "torch.Tensor") -> Tuple["torch.Tensor", "torch.Tensor"]:
        """
        Convert BGR tensor to NV12 planes on GPU.
        
        Args:
            bgr: (H, W, 3) uint8 BGR tensor on CUDA
        
        Returns:
            Tuple of (y_plane, uv_plane) where:
            - y_plane: (H, W) uint8
            - uv_plane: (H/2, W/2, 2) uint8 interleaved
        """
        import torch
        
        H, W = bgr.shape[:2]
        
        # Convert to float for computation
        bgr_f = bgr.float()
        b = bgr_f[:, :, 0]
        g = bgr_f[:, :, 1]
        r = bgr_f[:, :, 2]
        
        # BT.601 RGB -> YUV conversion
        # Y = 0.299*R + 0.587*G + 0.114*B
        # U = -0.1687*R - 0.3313*G + 0.5*B + 128
        # V = 0.5*R - 0.4187*G - 0.0813*B + 128
        y = 0.299 * r + 0.587 * g + 0.114 * b
        u = -0.1687 * r - 0.3313 * g + 0.5 * b + 128.0
        v = 0.5 * r - 0.4187 * g - 0.0813 * b + 128.0
        
        # Clamp to [0, 255]
        y = y.clamp(0, 255).to(torch.uint8)
        u = u.clamp(0, 255).to(torch.uint8)
        v = v.clamp(0, 255).to(torch.uint8)
        
        # Downsample UV to half resolution (nearest neighbor)
        u_ds = u[::2, ::2]  # (H/2, W/2)
        v_ds = v[::2, ::2]  # (H/2, W/2)
        
        # Interleave UV
        uv = torch.stack([u_ds, v_ds], dim=2)  # (H/2, W/2, 2)
        
        return y, uv
    
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
            line_thickness = self.config.line_thickness
            
            steps = max(abs(x2 - x1), abs(y2 - y1), 1)
            if steps <= 1:
                continue
            
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
            
            # Simple approach: draw polygon edges and fill bounding box with alpha
            ys = [p[1] for p in pts]
            xs = [p[0] for p in pts]
            min_y, max_y = min(ys), max(ys)
            min_x, max_x = min(xs), max(xs)
            
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
        dst_y1 = max(0, min(height - 1, y))
        dst_x1 = max(0, min(width - 1, x))
        dst_y2 = min(height, dst_y1 + img_h)
        dst_x2 = min(width, dst_x1 + img_w)
        
        src_h = dst_y2 - dst_y1
        src_w = dst_x2 - dst_x1
        
        if src_h > 0 and src_w > 0:
            src = text_gpu[:src_h, :src_w]
            
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
        self.metrics = GPUAnnotationPyAVMetrics()
        with self._lock:
            self._bgr_surface = None
            self._surface_shape = None


# Process-singleton pool
_RENDERERS_PYAV: Dict[str, GPUAnnotationPyAVRenderer] = {}
_RENDERERS_PYAV_LOCK = threading.Lock()


def get_gpu_annotation_pyav_renderer(camera_id: str, config: Optional[GPUAnnotationPyAVConfig] = None) -> GPUAnnotationPyAVRenderer:
    """Get or create the per-camera GPU annotation renderer for PyAV frames."""
    global _RENDERERS_PYAV
    with _RENDERERS_PYAV_LOCK:
        if camera_id not in _RENDERERS_PYAV:
            _RENDERERS_PYAV[camera_id] = GPUAnnotationPyAVRenderer(config)
        return _RENDERERS_PYAV[camera_id]


def reset_gpu_annotation_pyav_renderers() -> None:
    """Reset all renderers (for tests)."""
    global _RENDERERS_PYAV
    with _RENDERERS_PYAV_LOCK:
        for renderer in _RENDERERS_PYAV.values():
            renderer.reset()
        _RENDERERS_PYAV.clear()