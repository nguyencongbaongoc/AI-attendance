"""
ArcFace Face Recognition - GPU-accelerated face embedding extraction.

Runs ArcFace (glintr100) entirely on GPU using TensorRT (.engine) or ONNX Runtime (.onnx) with IO Binding.
Input: Aligned face crop (112x112) → Normalize → ArcFace TensorRT/ONNX → 512D embedding (L2 normalized).

Step 4/5: Added DB-driven gallery loading and thread-safe hot-reload.
"""

from __future__ import annotations

import logging
import time
import json
import threading
import asyncio
import numpy as np
import torch
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path

from pipeline_engine.memory.gpu_frame import GPUFrame
from pipeline_engine.config import get_config, get_model_config
from pipeline_engine.inference.tensorrt_engine import TensorRTExecutor, create_tensorrt_executor

logger = logging.getLogger(__name__)


@dataclass
class ArcFaceConfig:
    """Configuration for ArcFace recognition."""
    input_size: Tuple[int, int] = (112, 112)
    embedding_dim: int = 512
    mean: float = 127.5
    std: float = 128.0
    similarity_threshold: float = 0.6


@dataclass
class FaceEmbedding:
    """Face embedding result."""
    embedding: torch.Tensor  # (512,) float32 on CUDA, L2 normalized
    raw_embedding: torch.Tensor  # (512,) float32 before normalization
    raw_norm: float
    inference_time_ms: float
    detection_id: str
    frame_index: int = 0
    source_id: str = ""
    face_quality: float = 0.0
    
    def to_numpy(self) -> np.ndarray:
        """Convert to numpy array (copies to CPU)."""
        return self.embedding.cpu().numpy()
    
    def cosine_similarity(self, other: "FaceEmbedding") -> float:
        """Compute cosine similarity with another embedding."""
        return float(torch.dot(self.embedding, other.embedding))


class ArcFaceRecognizer:
    """
    ArcFace Face Recognizer running on GPU.
    
    Pipeline:
        Aligned face crop (112x112 BGR) 
            → Normalize: (x - 127.5) / 128.0 (GPU)
            → ArcFace TensorRT/ONNX (GPU, IO Binding)
            → L2 normalize embedding (GPU)
            → FaceEmbedding
    
    Supports both .engine (TensorRT) and .onnx (ONNX Runtime) model formats.
    """
    
    def __init__(
        self,
        model_path: str,
        config: Optional[ArcFaceConfig] = None,
        device_id: int = 0,
        cuda_stream: Optional[torch.cuda.Stream] = None,
    ):
        self.arcface_config = config or ArcFaceConfig()
        self.device_id = device_id
        self.device = f'cuda:{device_id}'
        
        # Store CUDA stream for parallel execution
        self.cuda_stream = cuda_stream
        
        # Backend selection based on model extension
        self._model_path = model_path
        self._use_tensorrt = model_path.endswith('.engine')
        
        # TensorRT executor (for .engine)
        self._trt_executor: Optional[TensorRTExecutor] = None
        
        # ONNX Runtime session (for .onnx)
        self._session: Optional[ort.InferenceSession] = None
        self._io_binding: Optional[ort.IOBinding] = None
        self._input_name: str = ""
        self._output_names: List[str] = []
        
        # Normalization constants
        self.input_h, self.input_w = self.arcface_config.input_size
        self.mean = torch.tensor(self.arcface_config.mean, device=self.device, dtype=torch.float32)
        self.std = torch.tensor(self.arcface_config.std, device=self.device, dtype=torch.float32)
        
        # --- Step 4/5: Matrix-based enrollment gallery for fast GPU similarity ---
        # (N, 512) GPU tensor for batched cosine similarity
        self.embeddings_matrix: Optional[torch.Tensor] = None
        self.identities: List[str] = []  # student_id per row
        self.metadata_lookup: Dict[str, Dict] = {}  # student_id -> {"name": ..., "class_id": ...}
        
        # Legacy dict-based storage (kept for compatibility)
        self._enrollment_embeddings: Dict[str, torch.Tensor] = {}  # person_id -> embedding
        self._enrollment_metadata: Dict[str, Dict] = {}
        
        # Thread-safe hot-reload (RLock for re-entrant safety)
        self._lock = threading.RLock()
        
        # Stats
        self._inference_count = 0
        self._total_inference_time = 0.0
        self._last_error: Optional[str] = None
        self._initialized = False
    
    def initialize(self) -> bool:
        """Initialize backend (TensorRT or ONNX Runtime) and load enrollment gallery from DB."""
        if self._initialized:
            return True
        
        try:
            # Initialize backend
            if self._use_tensorrt:
                if not self._initialize_tensorrt():
                    return False
            else:
                if not self._initialize_onnx():
                    return False
            
            # Load enrollment gallery from student database (cold boot)
            loaded_count = self.load_from_student_db_sync()
            if loaded_count > 0:
                logger.info(f"ArcFaceRecognizer: Initialized {loaded_count} enrolled identities from database.")
            else:
                logger.warning("ArcFaceRecognizer: No enrolled students found in DB. Falling back to directory scan.")
                self._fallback_load_from_files_sync()
            
            # Ensure matrix is initialized even if empty
            if self.embeddings_matrix is None:
                self.embeddings_matrix = torch.empty((0, self.arcface_config.embedding_dim), device=self.device, dtype=torch.float32)
                self.identities = []
                self.metadata_lookup = {}
            
            self._initialized = True
            logger.info(f"ArcFaceRecognizer: Cold boot complete. Gallery size: {self.embeddings_matrix.shape[0]}")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"ArcFaceRecognizer: Initialization failed: {e}")
            return False
    
    def _initialize_tensorrt(self) -> bool:
        """Initialize TensorRT executor for .engine file."""
        try:
            import onnxruntime as ort
        except ImportError:
            pass  # Not needed for TensorRT
        
        try:
            self._trt_executor = create_tensorrt_executor(self._model_path, self.device_id, self.cuda_stream)
            if not self._trt_executor.initialize():
                return False
            
            # Verify CUDA execution
            binding_info = self._trt_executor.get_binding_info()
            logger.info(f"ArcFaceRecognizer: Using TensorRT engine - {len(binding_info['inputs'])} inputs, {len(binding_info['outputs'])} outputs")
            
            self._initialized = True
            logger.info(f"ArcFaceRecognizer: Initialized TensorRT on device {self.device_id}")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"ArcFaceRecognizer: TensorRT initialization failed: {e}")
            return False
    
    def _initialize_onnx(self) -> bool:
        """Initialize ONNX Runtime session for .onnx file."""
        try:
            import onnxruntime as ort
        except ImportError:
            self._last_error = "onnxruntime not available"
            logger.error(f"ArcFaceRecognizer: {self._last_error}")
            return False
        
        try:
            session_options = ort.SessionOptions()
            session_options.enable_mem_pattern = True
            session_options.enable_cpu_mem_arena = True
            session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            session_options.intra_op_num_threads = 1
            session_options.inter_op_num_threads = 1
            
            self._session = ort.InferenceSession(
                self._model_path,
                sess_options=session_options,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            
            # Setup IO Binding for zero-copy
            self._io_binding = self._session.io_binding()
            
            # Get input/output names
            self._input_name = self._session.get_inputs()[0].name
            self._output_names = [o.name for o in self._session.get_outputs()]
            
            # Verify CUDA provider
            providers = self._session.get_providers()
            if "CUDAExecutionProvider" in providers:
                logger.info(f"ArcFaceRecognizer: Using CUDAExecutionProvider")
            else:
                logger.warning(f"ArcFaceRecognizer: CUDA not available, using {providers[0]}")
            
            self._initialized = True
            logger.info(f"ArcFaceRecognizer: Initialized ONNX Runtime on device {self.device_id}")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"ArcFaceRecognizer: ONNX Runtime initialization failed: {e}")
            return False
    
    def load_enrollment_database(
        self,
        embeddings_path: str,
        metadata_path: Optional[str] = None,
    ) -> bool:
        """
        Load enrollment database from NPY files (legacy composite format).
        
        Args:
            embeddings_path: Path to embeddings.npy (N, 512) float32
            metadata_path: Path to embeddings.npy.metadata.json
        """
        try:
            embeddings = np.load(embeddings_path)
            if embeddings.ndim != 2 or embeddings.shape[1] != self.arcface_config.embedding_dim:
                raise ValueError(f"Embeddings shape {embeddings.shape} != (N, {self.arcface_config.embedding_dim})")
            
            # Convert to GPU tensors
            self._enrollment_embeddings.clear()
            self._enrollment_metadata.clear()
            
            for i in range(embeddings.shape[0]):
                person_id = f"person_{i:04d}"  # Will be overridden by metadata
                emb_tensor = torch.from_numpy(embeddings[i]).to(self.device).float()
                # Ensure L2 normalized
                norm = torch.norm(emb_tensor)
                if norm > 0:
                    emb_tensor = emb_tensor / norm
                self._enrollment_embeddings[person_id] = emb_tensor
                self._enrollment_metadata[person_id] = {"index": i}
            
            # Load metadata if available
            if metadata_path:
                import json
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                
                # Handle both list and dict formats
                if isinstance(metadata, list):
                    for i, person_info in enumerate(metadata):
                        old_key = f"person_{i:04d}"
                        new_key = person_info.get("person_id", person_info.get("id", old_key))
                        if old_key in self._enrollment_embeddings:
                            self._enrollment_embeddings[new_key] = self._enrollment_embeddings.pop(old_key)
                            self._enrollment_metadata[new_key] = {**self._enrollment_metadata[old_key], **person_info}
                            self._enrollment_metadata.pop(old_key, None)
                elif isinstance(metadata, dict):
                    # Handle dict format with person_ids and sample_provenance
                    person_ids = metadata.get("person_ids", [])
                    sample_provenance = metadata.get("sample_provenance", [])
                    for i, person_id in enumerate(person_ids):
                        old_key = f"person_{i:04d}"
                        if old_key in self._enrollment_embeddings:
                            self._enrollment_embeddings[person_id] = self._enrollment_embeddings.pop(old_key)
                            prov = sample_provenance[i] if i < len(sample_provenance) else {}
                            self._enrollment_metadata[person_id] = {**self._enrollment_metadata[old_key], **prov}
                            self._enrollment_metadata.pop(old_key, None)
            
            # Also build the new matrix-based gallery
            self._build_matrix_gallery()
            
            logger.info(f"ArcFaceRecognizer: Loaded {len(self._enrollment_embeddings)} enrolled identities")
            return True
            
        except FileNotFoundError:
            logger.warning(f"ArcFaceRecognizer: Enrollment database not found at {embeddings_path}, continuing without enrollment")
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"ArcFaceRecognizer: Failed to load enrollment database: {e}")
            return False

    async def load_from_student_db(
        self,
        db_session_factory=None,
    ) -> int:
        """
        Load enrolled students directly from the database.
        
        Queries the active student roster from DB, loads per-person .npy embeddings,
        and builds the runtime (N, 512) feature matrix and lookup maps.
        
        Args:
            db_session_factory: Async session factory from app.db.session.get_session_factory()
            
        Returns:
            Number of identities loaded
        """
        # Use provided factory or try to import
        if db_session_factory is None:
            try:
                from app.db.session import get_session_factory
                session_factory = get_session_factory()
            except Exception:
                logger.warning("ArcFaceRecognizer: Could not get session factory, falling back to file scan")
                return await self._fallback_load_from_files()
        else:
            session_factory = db_session_factory
        
        try:
            async with session_factory() as session:
                from sqlalchemy import select
                from app.models.student import Student, EnrollmentStatusEnum
                
                # Query active enrolled students
                result = await session.execute(
                    select(Student).where(
                        Student.is_active == True,
                        Student.enrollment_status == EnrollmentStatusEnum.ENROLLED
                    )
                )
                students = result.scalars().all()
                
                return await self._load_from_student_list(students)
                
        except Exception as e:
            logger.warning(f"ArcFaceRecognizer: DB load failed: {e}, falling back to file scan")
            return await self._fallback_load_from_files()

    def load_from_student_db_sync(
        self,
        db_session_factory=None,
    ) -> int:
        """
        Synchronous load of enrolled students from database.
        Directly reads SQLite database to avoid event-loop deadlocks when called
        from sync/async contexts.
        """
        import sqlite3
        db_path = Path("app/data/school.db")
        if not db_path.exists():
            return self._fallback_load_from_files_sync()

        try:
            with sqlite3.connect(str(db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT student_id, full_name, class_id, gender, date_of_birth, embedding_path "
                    "FROM students WHERE is_active=1 AND enrollment_status='ENROLLED'"
                )
                rows = cursor.fetchall()

            embeddings_list = []
            identities = []
            metadata_lookup = {}
            for row in rows:
                sid, name, class_id, gender, dob, emb_path = row
                if not emb_path:
                    emb_path = f"app/data/embeddings/{sid}.npy"
                p = Path(emb_path)
                if not p.exists():
                    continue
                try:
                    emb_np = np.load(str(p)).astype(np.float32)
                    if emb_np.ndim == 1:
                        emb_np = emb_np.reshape(1, -1)
                    if emb_np.shape[1] != self.arcface_config.embedding_dim:
                        continue
                    norm = np.linalg.norm(emb_np)
                    if norm > 0:
                        emb_np = emb_np / norm
                    emb_tensor = torch.from_numpy(emb_np.squeeze(0)).to(self.device).float()
                    embeddings_list.append(emb_tensor)
                    identities.append(sid)
                    metadata_lookup[sid] = {
                        "name": name,
                        "class_id": class_id,
                        "gender": gender,
                        "date_of_birth": dob,
                    }
                except Exception as e:
                    logger.error(f"ArcFaceRecognizer: Failed to load embedding for {sid}: {e}")
                    continue

            with self._lock:
                if embeddings_list:
                    self.embeddings_matrix = torch.stack(embeddings_list, dim=0)
                else:
                    self.embeddings_matrix = torch.empty((0, self.arcface_config.embedding_dim), device=self.device, dtype=torch.float32)
                self.identities = identities
                self.metadata_lookup = metadata_lookup

                self._enrollment_embeddings.clear()
                self._enrollment_metadata.clear()
                for i, student_id in enumerate(identities):
                    self._enrollment_embeddings[student_id] = self.embeddings_matrix[i]
                    self._enrollment_metadata[student_id] = metadata_lookup.get(student_id, {})

            logger.info(f"ArcFaceRecognizer: Loaded {len(identities)} identities from student database")
            return len(identities)
        except Exception as e:
            logger.warning(f"ArcFaceRecognizer: Sync DB load error: {e}, falling back to file scan")
            return self._fallback_load_from_files_sync()

    async def _load_from_student_list(self, students: List["Student"]) -> int:
        """Load embeddings from a list of Student objects."""
        embeddings_list = []
        identities = []
        metadata_lookup = {}
        
        for student in students:
            # Determine embedding path
            embed_path = student.embedding_path
            if not embed_path:
                # Fallback to standard location
                embed_path = f"app/data/embeddings/{student.student_id}.npy"
            
            embed_path_obj = Path(embed_path)
            if not embed_path_obj.exists():
                logger.warning(f"ArcFaceRecognizer: Embedding file not found for {student.student_id}: {embed_path}")
                continue
            
            try:
                # Load embedding
                emb_np = np.load(str(embed_path_obj)).astype(np.float32)
                if emb_np.ndim == 1:
                    emb_np = emb_np.reshape(1, -1)
                
                # Ensure shape matches
                if emb_np.shape[1] != self.arcface_config.embedding_dim:
                    logger.warning(f"ArcFaceRecognizer: Embedding dim mismatch for {student.student_id}: {emb_np.shape}")
                    continue
                
                # L2 normalize
                norm = np.linalg.norm(emb_np)
                if norm > 0:
                    emb_np = emb_np / norm
                
                # Convert to GPU tensor
                emb_tensor = torch.from_numpy(emb_np.squeeze(0)).to(self.device).float()
                
                embeddings_list.append(emb_tensor)
                identities.append(student.student_id)
                metadata_lookup[student.student_id] = {
                    "name": student.full_name,
                    "class_id": student.class_id,
                    "gender": student.gender,
                    "date_of_birth": str(student.date_of_birth) if student.date_of_birth else None,
                }
                
            except Exception as e:
                logger.error(f"ArcFaceRecognizer: Failed to load embedding for {student.student_id}: {e}")
                continue
        
        # Build matrix gallery
        with self._lock:
            if embeddings_list:
                self.embeddings_matrix = torch.stack(embeddings_list, dim=0)  # (N, 512)
            else:
                self.embeddings_matrix = torch.empty((0, self.arcface_config.embedding_dim), device=self.device, dtype=torch.float32)
            self.identities = identities
            self.metadata_lookup = metadata_lookup
            
            # Also update legacy dict
            self._enrollment_embeddings.clear()
            self._enrollment_metadata.clear()
            for i, student_id in enumerate(identities):
                self._enrollment_embeddings[student_id] = self.embeddings_matrix[i]
                self._enrollment_metadata[student_id] = metadata_lookup.get(student_id, {})
        
        return len(identities)

    async def _fallback_load_from_files(self) -> int:
        """Fallback: scan app/data/embeddings/*.npy for any available embeddings."""
        return self._fallback_load_from_files_sync()

    def _fallback_load_from_files_sync(self) -> int:
        """Synchronous fallback: scan app/data/embeddings/*.npy for any available embeddings."""
        embeddings_dir = Path("app/data/embeddings")
        if not embeddings_dir.exists():
            logger.warning("ArcFaceRecognizer: No embeddings directory found")
            with self._lock:
                self.embeddings_matrix = torch.empty((0, self.arcface_config.embedding_dim), device=self.device, dtype=torch.float32)
                self.identities = []
                self.metadata_lookup = {}
            return 0
        
        npy_files = list(embeddings_dir.glob("*.npy"))
        if not npy_files:
            logger.warning("ArcFaceRecognizer: No .npy files found in embeddings directory")
            with self._lock:
                self.embeddings_matrix = torch.empty((0, self.arcface_config.embedding_dim), device=self.device, dtype=torch.float32)
                self.identities = []
                self.metadata_lookup = {}
            return 0
        
        embeddings_list = []
        identities = []
        metadata_lookup = {}
        
        for npy_file in npy_files:
            student_id = npy_file.stem
            try:
                emb_np = np.load(str(npy_file)).astype(np.float32)
                if emb_np.ndim == 1:
                    emb_np = emb_np.reshape(1, -1)
                
                if emb_np.shape[1] != self.arcface_config.embedding_dim:
                    continue
                
                norm = np.linalg.norm(emb_np)
                if norm > 0:
                    emb_np = emb_np / norm
                
                emb_tensor = torch.from_numpy(emb_np.squeeze(0)).to(self.device).float()
                embeddings_list.append(emb_tensor)
                identities.append(student_id)
                metadata_lookup[student_id] = {"name": student_id, "source": "file_scan"}
                
            except Exception as e:
                logger.error(f"ArcFaceRecognizer: Failed to load {npy_file}: {e}")
                continue
        
        with self._lock:
            if embeddings_list:
                self.embeddings_matrix = torch.stack(embeddings_list, dim=0)
            else:
                self.embeddings_matrix = torch.empty((0, self.arcface_config.embedding_dim), device=self.device, dtype=torch.float32)
            self.identities = identities
            self.metadata_lookup = metadata_lookup
        
        return len(identities)

    def _build_matrix_gallery(self) -> None:
        """Build the matrix-based gallery from legacy dict storage."""
        with self._lock:
            if not self._enrollment_embeddings:
                self.embeddings_matrix = torch.empty((0, self.arcface_config.embedding_dim), device=self.device, dtype=torch.float32)
                self.identities = []
                self.metadata_lookup = {}
                return
            
            person_ids = list(self._enrollment_embeddings.keys())
            embeddings_list = [self._enrollment_embeddings[pid] for pid in person_ids]
            
            self.embeddings_matrix = torch.stack(embeddings_list, dim=0)
            self.identities = person_ids
            self.metadata_lookup = {pid: self._enrollment_metadata.get(pid, {}) for pid in person_ids}

    def reload_gallery(self, db_session_factory=None) -> Dict[str, Any]:
        """
        Thread-safe hot-reload of the enrollment gallery.
        
        Called after new enrollments to update in-memory recognition matrix.
        
        Args:
            db_session_factory: Optional session factory (uses default if None)
            
        Returns:
            Status dict with enrolled count
        """
        with self._lock:
            count = self.load_from_student_db_sync(db_session_factory)
            logger.info(f"ArcFaceRecognizer: Hot-reloaded {count} identities from database")
            return {"status": "success", "enrolled_count": count}
    
    def preprocess(self, aligned_face: torch.Tensor) -> torch.Tensor:
        """
        Preprocess aligned face to ArcFace input format.
        
        Args:
            aligned_face: BGR tensor (112, 112, 3) uint8 or (1, 3, 112, 112) float32
            
        Returns:
            Preprocessed tensor: (1, 3, 112, 112) float32 normalized
        """
        # Handle numpy arrays
        if isinstance(aligned_face, np.ndarray):
            aligned_face = torch.from_numpy(aligned_face)
        
        # Move input to the correct device BEFORE any operations
        if hasattr(aligned_face, "to") and aligned_face.device != self.device:
            aligned_face = aligned_face.to(self.device)
        
        # Handle different input formats
        if aligned_face.dim() == 3:
            if aligned_face.shape[-1] == 3:
                # (H, W, 3) -> (1, 3, H, W)
                aligned_face = aligned_face.permute(2, 0, 1).unsqueeze(0)
            elif aligned_face.shape[0] == 3:
                # (3, H, W) -> (1, 3, H, W)
                aligned_face = aligned_face.unsqueeze(0)
            else:
                raise ValueError(f"Unexpected 3D tensor shape: {aligned_face.shape}")
        elif aligned_face.dim() == 4:
            if aligned_face.shape[1] != 3:
                raise ValueError(f"Expected 3 channels, got {aligned_face.shape[1]}")
        else:
            raise ValueError(f"Unexpected tensor dimensions: {aligned_face.dim()}")
        
        # Ensure float32
        aligned_face = aligned_face.float()
        
        # Resize if needed
        if aligned_face.shape[-2:] != (self.input_h, self.input_w):
            aligned_face = torch.nn.functional.interpolate(
                aligned_face,
                size=(self.input_h, self.input_w),
                mode='bilinear',
                align_corners=False
            )
        
        # Normalize: (x - 127.5) / 128.0
        normalized = (aligned_face - self.mean) / self.std
        
        return normalized.contiguous()
    
    def _bind_input(self, input_tensor: torch.Tensor) -> None:
        """Bind input tensor to IO Binding (ONNX Runtime)."""
        self._io_binding.bind_input(
            name=self._input_name,
            device_type='cuda',
            device_id=self.device_id,
            element_type=np.float32,
            shape=tuple(input_tensor.shape),
            buffer_ptr=input_tensor.data_ptr(),
        )
    
    def _bind_output(self) -> torch.Tensor:
        """Bind output tensor and return it (ONNX Runtime)."""
        out_tensor = torch.empty(
            (1, self.arcface_config.embedding_dim),
            dtype=torch.float32,
            device=self.device
        )
        
        self._io_binding.bind_output(
            name=self._output_names[0],
            device_type='cuda',
            device_id=self.device_id,
            element_type=np.float32,
            shape=(1, self.arcface_config.embedding_dim),
            buffer_ptr=out_tensor.data_ptr(),
        )
        
        return out_tensor
    
    def infer_raw(self, input_tensor: torch.Tensor) -> Tuple[torch.Tensor, float]:
        """Run raw inference (without L2 normalization) with TensorRT or ONNX Runtime."""
        if not self._initialized:
            self.initialize()
        
        if not self._initialized:
            raise RuntimeError("ArcFaceRecognizer not initialized")
        
        # Run inference within the camera's CUDA stream if provided
        stream = getattr(self, "cuda_stream", None)
        if stream is not None:
            with torch.cuda.stream(stream):
                if self._use_tensorrt:
                    return self._infer_raw_tensorrt(input_tensor)
                else:
                    return self._infer_raw_onnx(input_tensor)
        else:
            if self._use_tensorrt:
                return self._infer_raw_tensorrt(input_tensor)
            else:
                return self._infer_raw_onnx(input_tensor)
    
    def _infer_raw_tensorrt(self, input_tensor: torch.Tensor) -> Tuple[torch.Tensor, float]:
        """Run raw inference with TensorRT engine."""
        input_tensors = {self._trt_executor._input_names[0]: input_tensor}
        outputs = self._trt_executor.infer(input_tensors)
        # TensorRT output is already in self._trt_executor._output_tensors
        output_name = self._trt_executor._output_names[0]
        output_tensor = outputs[output_name].squeeze(0)
        # Note: TensorRTExecutor doesn't return per-inference timing directly
        # We'll track it here
        return output_tensor, 0.0  # timing handled by TensorRTExecutor
    
    def _infer_raw_onnx(self, input_tensor: torch.Tensor) -> Tuple[torch.Tensor, float]:
        """Run raw inference with ONNX Runtime."""
        # Clear previous bindings
        self._io_binding.clear_binding_inputs()
        self._io_binding.clear_binding_outputs()
        
        # Bind input
        self._bind_input(input_tensor)
        
        # Bind output
        output_tensor = self._bind_output()
        
        # Run inference
        start = time.perf_counter()
        self._session.run_with_iobinding(self._io_binding)
        
        # CRITICAL: Synchronize stream BEFORE returning output tensor
        # Prevents CPU from reading output while GPU is still writing
        stream = getattr(self, "cuda_stream", None)
        if stream is not None:
            stream.synchronize()
        else:
            torch.cuda.synchronize(self.device_id)
            
        inference_ms = (time.perf_counter() - start) * 1000
        
        # Update stats
        self._inference_count += 1
        self._total_inference_time += inference_ms
        
        return output_tensor.squeeze(0), inference_ms  # (512,), ms
    
    def infer_embedding(self, aligned_face: torch.Tensor) -> FaceEmbedding:
        """
        Run inference on aligned face and return L2-normalized embedding.
        
        Args:
            aligned_face: Aligned face tensor (112, 112, 3) BGR or (1, 3, 112, 112)
            
        Returns:
            FaceEmbedding with L2 normalized embedding
        """
        # Preprocess
        preprocessed = self.preprocess(aligned_face)
        
        # Raw inference
        raw_embedding, inference_ms = self.infer_raw(preprocessed)
        
        # L2 normalize
        raw_norm = float(torch.norm(raw_embedding))
        if raw_norm > 0:
            normalized_embedding = raw_embedding / raw_norm
        else:
            normalized_embedding = raw_embedding
            raw_norm = 0.0
        
        return FaceEmbedding(
            embedding=normalized_embedding,
            raw_embedding=raw_embedding,
            raw_norm=raw_norm,
            inference_time_ms=inference_ms,
            detection_id="",  # Set by caller
            frame_index=0,
            source_id="",
        )
    
    def identify(self, embedding: torch.Tensor, top_k: int = 5) -> List[Tuple[str, float]]:
        """
        Identify face against enrollment database using matrix-based GPU cosine similarity.
        
        Args:
            embedding: L2-normalized embedding (512,) on CUDA
            top_k: Number of top matches to return
            
        Returns:
            List of (person_id, similarity) sorted by similarity descending
        """
        if self.embeddings_matrix is None or self.embeddings_matrix.shape[0] == 0:
            return []
        
        # Matrix multiplication for batched cosine similarity (N, 512) @ (512,) -> (N,)
        similarities = torch.matmul(self.embeddings_matrix, embedding)  # (N,)
        
        # Get top-k
        top_k = min(top_k, self.embeddings_matrix.shape[0])
        top_values, top_indices = torch.topk(similarities, top_k)
        
        results = []
        for val, idx in zip(top_values.cpu().numpy(), top_indices.cpu().numpy()):
            person_id = self.identities[idx]
            similarity = float(val)
            # Only return matches above threshold
            if similarity >= self.arcface_config.similarity_threshold:
                results.append((person_id, similarity))
        
        return results

    def identify_with_metadata(
        self, 
        embedding: torch.Tensor, 
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Identify with full metadata."""
        matches = self.identify(embedding, top_k)
        results = []
        for person_id, similarity in matches:
            meta = self.metadata_lookup.get(person_id, {})
            results.append({
                "person_id": person_id,
                "similarity": similarity,
                "metadata": meta,
            })
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        backend = "tensorrt" if self._use_tensorrt else "onnxruntime"
        enrolled = self.embeddings_matrix.shape[0] if self.embeddings_matrix is not None else 0
        stats = {
            "model": "arcface",
            "backend": backend,
            "initialized": self._initialized,
            "enrolled_identities": enrolled,
            "inference_count": self._inference_count,
            "avg_inference_ms": (
                self._total_inference_time / self._inference_count 
                if self._inference_count > 0 else 0
            ),
            "last_error": self._last_error,
            "device_id": self.device_id,
        }
        
        if self._use_tensorrt and self._trt_executor:
            stats["providers"] = ["TensorRT"]
            stats["trt_stats"] = self._trt_executor.get_stats()
        elif self._session:
            stats["providers"] = self._session.get_providers()
        
        return stats

    def cleanup(self) -> None:
        """Release resources."""
        if self._use_tensorrt and self._trt_executor:
            self._trt_executor.cleanup()
            self._trt_executor = None
        else:
            self._session = None
            self._io_binding = None
        self._initialized = False
        self.embeddings_matrix = None
        self.identities = []
        self.metadata_lookup = {}
        self._enrollment_embeddings.clear()
        self._enrollment_metadata.clear()
        torch.cuda.empty_cache()


def create_arcface_recognizer(
    model_path: Optional[str] = None,
    device_id: int = 0,
) -> ArcFaceRecognizer:
    """Factory function to create ArcFace recognizer."""
    if model_path is None:
        config = get_config()
        model_config = get_model_config(config, "arcface")
        model_path = model_config.get("path", "models/arcface/glintr100.onnx")
    
    # Prefer .engine if available
    path = Path(model_path)
    if path.suffix == '.onnx':
        engine_path = path.with_suffix('.engine')
        if engine_path.exists():
            model_path = str(engine_path)
            logger.info(f"ArcFaceRecognizer: Using TensorRT engine at {engine_path}")
    
    config = ArcFaceConfig()
    return ArcFaceRecognizer(model_path, config, device_id)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    model_path = "models/arcface/glintr100.onnx"
    recognizer = create_arcface_recognizer(model_path)
    
    if recognizer.initialize():
        print("ArcFace recognizer initialized successfully!")
        print(f"Stats: {recognizer.get_stats()}")
        
        # Test loading enrollment
        if recognizer.load_enrollment_database("data/embeddings.npy", "data/embeddings.npy.metadata.json"):
            print("Enrollment database loaded!")
    else:
        print("ArcFace recognizer initialization failed")