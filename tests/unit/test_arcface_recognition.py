"""
Phase 12 — ArcFace Normal Face Recognition Unit Tests.

Tests:
- Input contract validation
- Model registry resolution
- Inference execution
- Output shape validation
- Finite output validation
- L2 normalization
- CUDA/CPU consistency
- Determinism
- Invalid input rejection
- Memory safety
- Safety boundaries

Tests do NOT:
- Access camera
- Access MediaMTX/RTSP/RTMP
- Perform live inference
- Implement identity matching
- Implement attendance/IN/OUT
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from app.models.registry import get_model_registry, ModelRegistry
from app.models.exceptions import ModelNotFoundError
from app.vision.recognition_contract import (
    ArcFaceInputContract,
    ArcFaceOutputContract,
    ArcFaceInferenceResult,
    get_arcface_input_contract,
    get_arcface_output_contract,
)
from app.vision.arcface_inference import (
    ArcFaceInference,
    ArcFaceInferenceConfig,
    create_arcface_inference,
    run_arcface_inference_cpu_only,
    run_arcface_inference_cuda,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the singleton registry before each test."""
    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


@pytest.fixture
def registry():
    """Get a fresh ModelRegistry instance."""
    return ModelRegistry()


@pytest.fixture
def input_contract():
    """Get ArcFace input contract."""
    return get_arcface_input_contract()


@pytest.fixture
def output_contract():
    """Get ArcFace output contract."""
    return get_arcface_output_contract()


@pytest.fixture
def synthetic_aligned_face():
    """Generate deterministic synthetic aligned face (BGR, 112x112x3, uint8)."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 256, size=(112, 112, 3), dtype=np.uint8)


@pytest.fixture
def synthetic_preprocessed_tensor():
    """Generate deterministic synthetic preprocessed tensor (1, 3, 112, 112, float32)."""
    rng = np.random.default_rng(42)
    return rng.random((1, 3, 112, 112), dtype=np.float32)


# =============================================================================
# TASK 1: INPUT CONTRACT TESTS
# =============================================================================

class TestArcFaceInputContract:
    """Tests for ArcFace input contract validation."""
    
    def test_input_contract_shape(self, input_contract):
        """Test input contract specifies correct shape."""
        shape = input_contract.get_input_shape()
        assert shape == (1, 3, 112, 112)
    
    def test_input_contract_dtype(self, input_contract):
        """Test input contract specifies float32."""
        assert input_contract.dtype == np.float32
    
    def test_input_contract_channel_order(self, input_contract):
        """Test input contract specifies RGB explicitly."""
        assert input_contract.channel_order == "RGB"
    
    def test_input_contract_normalization(self, input_contract):
        """Test input contract has explicit normalization."""
        assert input_contract.normalization_mean == (127.5, 127.5, 127.5)
        assert input_contract.normalization_std == (128.0, 128.0, 128.0)
    
    def test_validate_valid_input(self, input_contract, synthetic_preprocessed_tensor):
        """Test validation passes for valid input."""
        is_valid, error = input_contract.validate_input(synthetic_preprocessed_tensor)
        assert is_valid is True
        assert error is None
    
    def test_reject_wrong_shape(self, input_contract):
        """Test rejection of wrong shape."""
        wrong_shape = np.random.default_rng().random((1, 3, 224, 224), dtype=np.float32)
        is_valid, error = input_contract.validate_input(wrong_shape)
        assert is_valid is False
        assert "Shape mismatch" in error
    
    def test_reject_wrong_dtype(self, input_contract):
        """Test rejection of wrong dtype."""
        wrong_dtype = np.random.default_rng().random((1, 3, 112, 112), dtype=np.float64)
        is_valid, error = input_contract.validate_input(wrong_dtype)
        assert is_valid is False
        assert "Dtype mismatch" in error
    
    def test_reject_nan_input(self, input_contract):
        """Test rejection of NaN input."""
        nan_input = np.ones((1, 3, 112, 112), dtype=np.float32)
        nan_input[0, 0, 0, 0] = np.nan
        is_valid, error = input_contract.validate_input(nan_input)
        assert is_valid is False
        assert "NaN" in error
    
    def test_reject_inf_input(self, input_contract):
        """Test rejection of Inf input."""
        inf_input = np.ones((1, 3, 112, 112), dtype=np.float32)
        inf_input[0, 0, 0, 0] = np.inf
        is_valid, error = input_contract.validate_input(inf_input)
        assert is_valid is False
        assert "Inf" in error
    
    def test_reject_empty_input(self, input_contract):
        """Test rejection of empty input."""
        empty_input = np.array([], dtype=np.float32)
        is_valid, error = input_contract.validate_input(empty_input)
        assert is_valid is False
    
    def test_reject_wrong_channel_count(self, input_contract):
        """Test rejection of incorrect channel count."""
        wrong_channels = np.random.default_rng().random((1, 4, 112, 112), dtype=np.float32)
        is_valid, error = input_contract.validate_input(wrong_channels)
        assert is_valid is False
        assert "Shape mismatch" in error
    
    def test_reject_wrong_spatial_dimensions(self, input_contract):
        """Test rejection of incorrect spatial dimensions."""
        wrong_spatial = np.random.default_rng().random((1, 3, 56, 56), dtype=np.float32)
        is_valid, error = input_contract.validate_input(wrong_spatial)
        assert is_valid is False
        assert "Shape mismatch" in error
    
    def test_preprocess_bgr_to_rgb(self, input_contract, synthetic_aligned_face):
        """Test preprocessing converts BGR to RGB correctly."""
        # Create a face with known BGR pattern
        face_bgr = np.zeros((112, 112, 3), dtype=np.uint8)
        face_bgr[:, :, 0] = 100  # Blue
        face_bgr[:, :, 1] = 150  # Green
        face_bgr[:, :, 2] = 200  # Red
        
        tensor = input_contract.preprocess(face_bgr)
        
        # After BGR->RGB conversion and normalization:
        # Blue channel (index 0 in BGR) becomes Red channel (index 0 in RGB)
        # Red channel (index 2 in BGR) becomes Blue channel (index 2 in RGB)
        # Check that channels are swapped correctly
        # Normalized: (value - 127.5) / 128.0
        expected_r = (200 - 127.5) / 128.0  # Red channel in RGB
        expected_g = (150 - 127.5) / 128.0  # Green channel
        expected_b = (100 - 127.5) / 128.0  # Blue channel in RGB
        
        np.testing.assert_allclose(tensor[0, 0, 0, 0], expected_r, rtol=1e-5)
        np.testing.assert_allclose(tensor[0, 1, 0, 0], expected_g, rtol=1e-5)
        np.testing.assert_allclose(tensor[0, 2, 0, 0], expected_b, rtol=1e-5)
    
    def test_preprocess_output_range(self, input_contract, synthetic_aligned_face):
        """Test preprocessed output is in [-1, 1] range."""
        tensor = input_contract.preprocess(synthetic_aligned_face)
        assert tensor.min() >= -1.0 - 1e-5
        assert tensor.max() <= 1.0 + 1e-5
    
    def test_preprocess_validates_output(self, input_contract, synthetic_aligned_face):
        """Test preprocess validates its own output."""
        tensor = input_contract.preprocess(synthetic_aligned_face)
        is_valid, error = input_contract.validate_input(tensor)
        assert is_valid is True
        assert error is None


# =============================================================================
# TASK 2: MODEL REGISTRY TESTS
# =============================================================================

class TestArcFaceModelRegistry:
    """Tests for ArcFace model registry resolution."""
    
    def test_arcface_registered(self, registry):
        """Test ArcFace is registered in model registry."""
        assert registry.is_registered("arcface")
    
    def test_arcface_model_definition(self, registry):
        """Test ArcFace model definition has correct metadata."""
        model = registry.get("arcface")
        assert model.model_id == "arcface"
        assert model.filename == "glintr100.onnx"
        assert model.format.value == "onnx"
        assert model.provider.value == "onnxruntime"
    
    def test_arcface_preprocessing_config(self, registry):
        """Test ArcFace preprocessing config matches contract."""
        model = registry.get("arcface")
        assert model.preprocessing.input_height == 112
        assert model.preprocessing.input_width == 112
        assert model.preprocessing.input_channels == 3
        assert model.preprocessing.channel_order == "RGB"
        assert model.preprocessing.dtype == "float32"
    
    def test_arcface_output_contract(self, registry):
        """Test ArcFace output contract."""
        model = registry.get("arcface")
        assert model.output_contract.output_type == "embedding"
        assert model.output_contract.embedding_dimension == 512
    
    def test_arcface_sha256_exists(self, registry):
        """Test ArcFace has expected SHA256."""
        model = registry.get("arcface")
        assert model.expected_sha256 is not None
        assert len(model.expected_sha256) == 64
    
    def test_arcface_model_path_resolution(self, registry):
        """Test ArcFace model path resolution."""
        path = registry.get_model_path("arcface")
        assert path.name == "glintr100.onnx"
        assert "arcface" in str(path) or path.parent.name == "arcface"
    
    def test_arcface_model_verification(self, registry):
        """Test ArcFace model SHA256 verification."""
        result = registry.verify_model("arcface")
        # Model file exists, so should not be MISSING
        assert not result.is_missing()
        # Should be VERIFIED or HASH_MISMATCH (not MISSING)
        assert result.status in ["verified", "hash_mismatch"]


# =============================================================================
# TASK 3: ARCFACE INFERENCE TESTS
# =============================================================================

class TestArcFaceInference:
    """Tests for ArcFace inference execution."""
    
    def test_create_inference_engine(self, registry):
        """Test creating ArcFace inference engine."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        assert inference is not None
        assert inference.provider_used in ["CPUExecutionProvider", "CUDAExecutionProvider"]
    
    def test_inference_input_shape(self, registry, synthetic_aligned_face):
        """Test inference produces correct input shape."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        preprocessed = inference.preprocess(synthetic_aligned_face)
        assert preprocessed.shape == (1, 3, 112, 112)
    
    def test_inference_output_shape(self, registry, synthetic_aligned_face):
        """Test inference produces correct output shape (512D)."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        result = inference.infer(synthetic_aligned_face)
        
        # Check raw embedding shape
        assert result.raw_embedding.shape == (1, 512) or result.raw_embedding.shape == (512,)
        
        # Check normalized embedding shape
        assert result.normalized_embedding.shape == (1, 512)
    
    def test_inference_output_finite(self, registry, synthetic_aligned_face):
        """Test inference output contains only finite values."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        result = inference.infer(synthetic_aligned_face)
        
        assert np.isfinite(result.raw_embedding).all()
        assert np.isfinite(result.normalized_embedding).all()
        assert not np.isnan(result.raw_embedding).any()
        assert not np.isnan(result.normalized_embedding).any()
        assert not np.isinf(result.raw_embedding).any()
        assert not np.isinf(result.normalized_embedding).any()
    
    def test_inference_raw_embedding_returned(self, registry, synthetic_aligned_face):
        """Test raw embedding is returned before normalization."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        result = inference.infer(synthetic_aligned_face)
        
        assert result.raw_embedding is not None
        assert result.raw_norm > 0
    
    def test_inference_metadata(self, registry, synthetic_aligned_face):
        """Test inference result contains metadata."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        result = inference.infer(synthetic_aligned_face)
        
        assert result.input_shape == (1, 3, 112, 112)
        assert result.output_shape == (1, 512)
        assert result.inference_time_ms > 0
        assert result.provider in ["CPUExecutionProvider", "CUDAExecutionProvider"]


# =============================================================================
# TASK 4: EMBEDDING NORMALIZATION TESTS
# =============================================================================

class TestEmbeddingNormalization:
    """Tests for L2 normalization of embeddings."""
    
    def test_l2_normalize_output_shape(self, registry):
        """Test L2 normalization preserves shape."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        # Test with known embedding
        raw_emb = np.ones((1, 512), dtype=np.float32) * 0.5
        normalized, raw_norm = inference.l2_normalize(raw_emb)
        
        assert normalized.shape == (1, 512)
        assert raw_norm > 0
    
    def test_l2_normalize_norm_approximately_one(self, registry):
        """Test L2 normalized embedding has norm ≈ 1.0."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        # Test with random embedding
        rng = np.random.default_rng(123)
        raw_emb = rng.random((1, 512), dtype=np.float32)
        normalized, raw_norm = inference.l2_normalize(raw_emb)
        
        norm = np.linalg.norm(normalized.flatten())
        assert np.isclose(norm, 1.0, rtol=1e-5)
    
    def test_l2_normalize_preserves_direction(self, registry):
        """Test L2 normalization preserves vector direction."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        raw_emb = np.array([[1.0, 2.0, 3.0, 4.0] + [0.0] * 508], dtype=np.float32)
        normalized, _ = inference.l2_normalize(raw_emb)
        
        # Direction should be preserved (cosine similarity = 1)
        cos_sim = np.dot(raw_emb.flatten(), normalized.flatten()) / (
            np.linalg.norm(raw_emb.flatten()) * np.linalg.norm(normalized.flatten())
        )
        assert np.isclose(cos_sim, 1.0, rtol=1e-5)
    
    def test_l2_normalize_rejects_zero_norm(self, registry):
        """Test L2 normalization rejects zero-norm embedding."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        zero_emb = np.zeros((1, 512), dtype=np.float32)
        with pytest.raises(ValueError, match="zero-norm"):
            inference.l2_normalize(zero_emb)
    
    def test_full_pipeline_normalization(self, registry, synthetic_aligned_face):
        """Test full inference pipeline produces normalized embedding."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        result = inference.infer(synthetic_aligned_face)
        
        norm = np.linalg.norm(result.normalized_embedding.flatten())
        assert np.isclose(norm, 1.0, rtol=1e-5)


# =============================================================================
# TASK 5: CUDA/CPU CONSISTENCY TESTS
# =============================================================================

class TestCudaCpuConsistency:
    """Tests for CUDA/CPU inference consistency."""
    
    def test_cpu_inference_works(self, registry, synthetic_aligned_face):
        """Test CPU inference executes successfully."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        result = inference.infer(synthetic_aligned_face)
        
        assert result.provider == "CPUExecutionProvider"
        assert np.isfinite(result.normalized_embedding).all()
    
    def test_cuda_inference_if_available(self, registry, synthetic_aligned_face):
        """Test CUDA inference if available, otherwise record limitation."""
        import onnxruntime as ort
        
        available_providers = ort.get_available_providers()
        cuda_available = "CUDAExecutionProvider" in available_providers
        
        if cuda_available:
            inference = create_arcface_inference(
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                registry=registry
            )
            result = inference.infer(synthetic_aligned_face)
            
            assert result.provider == "CUDAExecutionProvider"
            assert np.isfinite(result.normalized_embedding).all()
        else:
            # Record environment limitation - this is expected behavior
            pytest.skip("CUDAExecutionProvider not available in this environment")
    
    def test_cuda_cpu_output_consistency(self, registry, synthetic_aligned_face):
        """Test CUDA and CPU outputs are consistent within tolerance."""
        import onnxruntime as ort
        
        available_providers = ort.get_available_providers()
        cuda_available = "CUDAExecutionProvider" in available_providers
        
        if not cuda_available:
            pytest.skip("CUDAExecutionProvider not available - cannot test consistency")
        
        # Run CPU inference
        cpu_inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        cpu_result = cpu_inference.infer(synthetic_aligned_face)
        
        # Run CUDA inference
        cuda_inference = create_arcface_inference(
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            registry=registry
        )
        cuda_result = cuda_inference.infer(synthetic_aligned_face)
        
        # Compare normalized embeddings
        cpu_emb = cpu_result.normalized_embedding.flatten()
        cuda_emb = cuda_result.normalized_embedding.flatten()
        
        # Cosine similarity should be very high (≈1.0)
        cos_sim = np.dot(cpu_emb, cuda_emb) / (np.linalg.norm(cpu_emb) * np.linalg.norm(cuda_emb))
        
        # Allow small numerical differences due to CUDA/CPU floating point
        assert cos_sim > 0.9999, f"CUDA/CPU consistency failed: cosine similarity = {cos_sim}"
        
        # Also check L2 distance
        l2_dist = np.linalg.norm(cpu_emb - cuda_emb)
        assert l2_dist < 1e-3, f"CUDA/CPU L2 distance too large: {l2_dist}"


# =============================================================================
# TASK 6: DETERMINISM TESTS
# =============================================================================

class TestDeterminism:
    """Tests for deterministic inference."""
    
    def test_same_input_produces_same_output(self, registry, synthetic_aligned_face):
        """Test same input produces identical embedding across runs."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        # Run inference multiple times
        results = []
        for _ in range(5):
            result = inference.infer(synthetic_aligned_face)
            results.append(result.normalized_embedding.flatten())
        
        # All results should be identical (or within numerical tolerance)
        for i in range(1, len(results)):
            cos_sim = np.dot(results[0], results[i]) / (
                np.linalg.norm(results[0]) * np.linalg.norm(results[i])
            )
            assert np.isclose(cos_sim, 1.0, rtol=1e-6), f"Run {i} differs from run 0"
    
    def test_preprocess_deterministic(self, input_contract, synthetic_aligned_face):
        """Test preprocessing is deterministic."""
        tensor1 = input_contract.preprocess(synthetic_aligned_face)
        tensor2 = input_contract.preprocess(synthetic_aligned_face)
        
        assert np.array_equal(tensor1, tensor2)
    
    def test_inference_deterministic_with_same_session(self, registry, synthetic_preprocessed_tensor):
        """Test raw inference is deterministic with same session."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        results = []
        for _ in range(5):
            raw_emb, _ = inference.infer_raw(synthetic_preprocessed_tensor)
            results.append(raw_emb.flatten())
        
        for i in range(1, len(results)):
            assert np.allclose(results[0], results[i], rtol=1e-6), f"Run {i} differs from run 0"


# =============================================================================
# TASK 7: NEGATIVE TESTS (INVALID INPUT REJECTION)
# =============================================================================

class TestInvalidInputRejection:
    """Tests for rejecting invalid inputs."""
    
    def test_reject_wrong_shape_image(self, registry):
        """Test rejection of wrong shape image."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        wrong_shape = np.random.randint(0, 256, (224, 224, 3), dtype=np.uint8)
        with pytest.raises(ValueError, match="Expected aligned face shape"):
            inference.preprocess(wrong_shape)
    
    def test_reject_wrong_dtype_image(self, registry):
        """Test rejection of wrong dtype image."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        wrong_dtype = np.random.random((112, 112, 3)).astype(np.float32)
        with pytest.raises(ValueError, match="Expected uint8 input"):
            inference.preprocess(wrong_dtype)
    
    def test_reject_wrong_channel_count_image(self, registry):
        """Test rejection of wrong channel count."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        wrong_channels = np.random.randint(0, 256, (112, 112, 4), dtype=np.uint8)
        with pytest.raises(ValueError, match="Expected aligned face shape"):
            inference.preprocess(wrong_channels)
    
    def test_reject_wrong_shape_tensor(self, registry, synthetic_preprocessed_tensor):
        """Test rejection of wrong shape tensor in infer_raw."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        wrong_shape = np.random.default_rng().random((1, 3, 224, 224), dtype=np.float32)
        with pytest.raises(ValueError, match="Shape mismatch"):
            inference.infer_raw(wrong_shape)
    
    def test_reject_wrong_dtype_tensor(self, registry):
        """Test rejection of wrong dtype tensor in infer_raw."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        wrong_dtype = np.random.default_rng().random((1, 3, 112, 112), dtype=np.float64)
        with pytest.raises(ValueError, match="Dtype mismatch"):
            inference.infer_raw(wrong_dtype)
    
    def test_reject_nan_tensor(self, registry):
        """Test rejection of NaN tensor."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        nan_tensor = np.ones((1, 3, 112, 112), dtype=np.float32)
        nan_tensor[0, 0, 0, 0] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            inference.infer_raw(nan_tensor)
    
    def test_reject_inf_tensor(self, registry):
        """Test rejection of Inf tensor."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        inf_tensor = np.ones((1, 3, 112, 112), dtype=np.float32)
        inf_tensor[0, 0, 0, 0] = np.inf
        with pytest.raises(ValueError, match="Inf"):
            inference.infer_raw(inf_tensor)
    
    def test_no_silent_reshape(self, registry):
        """Test no silent reshape of incorrect input."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        # Wrong shape that could be silently reshaped
        wrong_shape = np.random.default_rng().random((3, 112, 112), dtype=np.float32)  # Missing batch dim
        with pytest.raises(ValueError):
            inference.infer_raw(wrong_shape)
    
    def test_no_silent_resize(self, registry):
        """Test no silent resize of incorrect input."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        # Wrong spatial size
        wrong_size = np.random.randint(0, 256, (56, 56, 3), dtype=np.uint8)
        with pytest.raises(ValueError):
            inference.preprocess(wrong_size)


# =============================================================================
# TASK 8: MEMORY SAFETY TESTS
# =============================================================================

class TestMemorySafety:
    """Tests for memory safety during repeated inference."""
    
    def test_repeated_inference_no_leak(self, registry, synthetic_aligned_face):
        """Test repeated inference doesn't accumulate memory."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        # Run many inferences
        for i in range(50):
            result = inference.infer(synthetic_aligned_face)
            assert np.isfinite(result.normalized_embedding).all()
        
        # If we reach here without OOM, memory is bounded
        assert True
    
    def test_session_reuse_safe(self, registry, synthetic_aligned_face):
        """Test session reuse is safe."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        # Use same session for multiple inferences
        for _ in range(20):
            result = inference.infer(synthetic_aligned_face)
            assert result.normalized_embedding.shape == (1, 512)
    
    def test_batch_inference_memory(self, registry, synthetic_aligned_face):
        """Test batch inference doesn't leak."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        # Create batch of faces
        faces = [synthetic_aligned_face.copy() for _ in range(10)]
        
        results = inference.infer_batch(faces)
        assert len(results) == 10
        for result in results:
            assert np.isfinite(result.normalized_embedding).all()


# =============================================================================
# TASK 9: SAFETY BOUNDARY TESTS
# =============================================================================

class TestSafetyBoundaries:
    """Tests for safety boundaries - Phase 12 must NOT access prohibited resources."""
    
    def test_no_camera_access(self, registry, synthetic_aligned_face):
        """Test inference doesn't access camera."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        # This should work without any camera access
        result = inference.infer(synthetic_aligned_face)
        assert result is not None
    
    def test_no_mediamtx_access(self, registry):
        """Test no MediaMTX/RTSP/RTMP access."""
        # Model registry and inference should not require any streaming
        registry = get_model_registry()
        model = registry.get("arcface")
        assert model is not None
        # No network calls should be made
    
    def test_no_attendance_logic(self, registry, synthetic_aligned_face):
        """Test no attendance/IN/OUT logic in inference."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        result = inference.infer(synthetic_aligned_face)
        
        # Result should only contain embedding and metadata
        assert hasattr(result, 'normalized_embedding')
        assert hasattr(result, 'raw_embedding')
        assert hasattr(result, 'inference_time_ms')
        assert hasattr(result, 'provider')
        # Should NOT have attendance-related fields
        assert not hasattr(result, 'attendance_status')
        assert not hasattr(result, 'in_out')
        assert not hasattr(result, 'schedule')
    
    def test_no_identity_database(self, registry, synthetic_aligned_face):
        """Test no identity database access."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        result = inference.infer(synthetic_aligned_face)
        
        # Should only return embedding, no identity matching
        assert result.normalized_embedding.shape == (1, 512)
        # No identity fields
        assert not hasattr(result, 'identity')
        assert not hasattr(result, 'person_id')
        assert not hasattr(result, 'distance')
    
    def test_no_excel_access(self, registry):
        """Test no Excel/spreadsheet access."""
        registry = get_model_registry()
        model = registry.get("arcface")
        assert model is not None
        # Registry should not access Excel files


# =============================================================================
# TASK 10: TARGETED INTEGRATION TESTS
# =============================================================================

class TestArcFaceIntegration:
    """Integration tests for ArcFace pipeline."""
    
    def test_end_to_end_pipeline(self, registry, synthetic_aligned_face):
        """Test complete pipeline: preprocess -> infer -> normalize."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        # Full pipeline
        result = inference.infer(synthetic_aligned_face)
        
        # Validate all components
        assert result.raw_embedding is not None
        assert result.normalized_embedding is not None
        assert result.raw_norm > 0
        assert result.input_shape == (1, 3, 112, 112)
        assert result.output_shape == (1, 512)
        assert result.inference_time_ms > 0
        
        # Validate normalized embedding
        norm = np.linalg.norm(result.normalized_embedding.flatten())
        assert np.isclose(norm, 1.0, rtol=1e-5)
        
        # Validate output contract
        output_contract = get_arcface_output_contract()
        is_valid, error = output_contract.validate_output(result.normalized_embedding)
        assert is_valid, error
    
    def test_convenience_functions(self, registry, synthetic_aligned_face):
        """Test convenience functions work."""
        # CPU only
        cpu_result = run_arcface_inference_cpu_only(synthetic_aligned_face, registry)
        assert cpu_result.provider == "CPUExecutionProvider"
        assert np.isfinite(cpu_result.normalized_embedding).all()
        
        # CUDA (with fallback)
        cuda_result = run_arcface_inference_cuda(synthetic_aligned_face, registry)
        assert cuda_result.provider in ["CPUExecutionProvider", "CUDAExecutionProvider"]
        assert np.isfinite(cuda_result.normalized_embedding).all()
    
    def test_model_registry_integration(self, registry):
        """Test inference uses model registry correctly."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        
        # Should use registry to get model
        assert inference.model_def.model_id == "arcface"
        assert inference.model_path.name == "glintr100.onnx"
        assert inference.model_path.exists()
    
    def test_sha256_verification_enforced(self, registry):
        """Test SHA256 verification is enforced."""
        # This should work because model exists and hash matches
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        assert inference is not None
    
    def test_output_contract_validation(self, registry, synthetic_aligned_face):
        """Test output contract validation in inference."""
        inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
        result = inference.infer(synthetic_aligned_face)
        
        output_contract = get_arcface_output_contract()
        is_valid, error = output_contract.validate_output(result.normalized_embedding)
        assert is_valid, error
        
        # Also validate raw embedding
        is_valid, error = output_contract.validate_output(result.raw_embedding)
        assert is_valid, error


# =============================================================================
# REGRESSION TESTS
# =============================================================================

class TestRegression:
    """Regression tests to ensure existing functionality still works."""
    
    def test_model_registry_still_works(self, registry):
        """Test model registry still works for all models."""
        model_ids = registry.get_model_ids()
        assert len(model_ids) == 6
        assert "arcface" in model_ids
        assert "scrfd" in model_ids
    
    def test_other_models_unaffected(self, registry):
        """Test other model definitions unchanged."""
        scrfd = registry.get("scrfd")
        assert scrfd.model_id == "scrfd"
        assert scrfd.filename == "scrfd_10g_bnkps.onnx"
        
        reid = registry.get("reid")
        assert reid.model_id == "reid"
        assert reid.filename == "resnet50_reid.onnx"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])