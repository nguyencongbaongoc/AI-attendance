"""
Phase 44.X.4 R3.13-SCRFD-FIX — Regression tests for the SCRFD preprocessing
normalization bug.

Background:
    The SCRFD preprocessing contract declares input_range=(0.0, 1.0) (i.e.
    the tensor is expected to be in [0, 1] BEFORE ImageNet mean/std
    normalization). The previous `_normalize` implementation only divided
    by 255 when contract.input_range implied a [0, 255] domain, so for SCRFD
    the /255 step was SKIPPED, raw uint8 pixel values (~0..255) were fed
    straight into `(x - mean) / std`, producing ~500-scale garbage tensors
    and unbounded false-positive face detections.

These tests pin the correct behaviour:
  * uint8 / [0, 255] input is divided by 255 before mean/std
  * resulting values are in the normalized magnitude range (not ~500)
  * float32 [0, 1] input is NOT divided again (no double /255)
  * shape / dtype / layout match the SCRFD contract
  * representative values demonstrate the ~500-scale bug is gone
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Allow `python -m pytest tests/...` from project root
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data.preprocessing import UnifiedPreprocessor  # noqa: E402
from app.data.contracts import get_model_contract  # noqa: E402


# SCRFD ImageNet stats (must match app/data/contracts.py)
SCRFD_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
SCRFD_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _build_scrfd_uint8_frame(h: int = 64, w: int = 64) -> np.ndarray:
    """Build a deterministic uint8 BGR frame (the preprocessor converts to RGB)."""
    # Constant mid-gray = 128 on all three channels.
    img = np.full((h, w, 3), 128, dtype=np.uint8)
    return img


def _build_scrfd_zero_to_one_float_frame(h: int = 64, w: int = 64) -> np.ndarray:
    """Build a deterministic float32 RGB frame already in [0, 1]."""
    img = np.full((h, w, 3), 0.5, dtype=np.float32)
    return img


class TestScrfdPreprocessingNormalizationFix:
    """R3.13-SCRFD-FIX — focused regression coverage."""

    def test_scrfd_contract_input_range_is_unit(self):
        """SCRFD contract MUST declare input_range=(0, 1) — pre-mean/std domain."""
        contract = get_model_contract("scrfd")
        assert contract.preprocessing.input_range == (0.0, 1.0), (
            "SCRFD contract input_range changed; this test suite assumes (0, 1)."
        )

    def test_uint8_frame_is_scaled_before_mean_std(self):
        """uint8 source frame must be divided by 255 BEFORE mean/std.

        Reproduces the original bug: with the buggy _normalize the mean/std
        of a 128-valued uint8 frame produces ~((128-0.5)/0.23) ≈ 554, i.e.
        the ~500-scale garbage. With the fix, the value must be near
        (0.502 - 0.5) / 0.229 ≈ 0.009.
        """
        preprocessor = UnifiedPreprocessor(model_id="scrfd")
        frame_uint8 = _build_scrfd_uint8_frame(64, 64)

        result = preprocessor._normalize(frame_uint8)

        # Output dtype is float32
        assert result.dtype == np.float32

        # Per-pixel ImageNet-normalized value for a flat 128/255 frame:
        #   x = (128/255 - mean) / std
        expected = (128.0 / 255.0 - SCRFD_MEAN) / SCRFD_STD
        # Result is HWC; check the central pixel
        cy, cx = 32, 32
        np.testing.assert_allclose(
            result[cy, cx, :],
            expected,
            rtol=1e-4,
            atol=1e-5,
            err_msg=(
                "uint8 /255 scaling was not applied BEFORE mean/std. "
                "If this is ~500, the R3.13-SCRFD bug has regressed."
            ),
        )

    def test_uint8_value_is_not_in_garbage_500_range(self):
        """Explicit anti-regression: the ~500-scale bug must not return.

        The pre-fix implementation produced values in the ~500 range for
        any uint8 frame. After the fix the absolute value of any
        per-channel output must be well under 10 for the canonical
        mid-gray / black / white test points.
        """
        preprocessor = UnifiedPreprocessor(model_id="scrfd")

        for value in (0, 64, 128, 192, 255):
            frame = np.full((8, 8, 3), value, dtype=np.uint8)
            out = preprocessor._normalize(frame)
            assert np.all(np.abs(out) < 10.0), (
                f"Normalized output for uint8={value} is in ~500-scale "
                f"garbage range: min={out.min()}, max={out.max()}"
            )

    def test_normalized_values_are_in_expected_magnitude(self):
        """ImageNet-normalized pixels for a uint8 [0,255] input should land
        in a tight band around (x/255 - mean)/std."""
        preprocessor = UnifiedPreprocessor(model_id="scrfd")
        frame = _build_scrfd_uint8_frame(16, 16)
        out = preprocessor._normalize(frame)

        # For each channel c: every pixel equals
        #   (128/255 - SCRFD_MEAN[c]) / SCRFD_STD[c]
        expected = (128.0 / 255.0 - SCRFD_MEAN) / SCRFD_STD
        # Each channel must be constant for a constant-input frame.
        for c in range(3):
            chan = out[..., c]
            np.testing.assert_allclose(chan, expected[c], rtol=1e-4, atol=1e-5)
            # The values must be in the typical ImageNet normalized band,
            # definitely NOT in the 100s or 1000s.
            assert abs(chan[0, 0]) < 5.0, (
                f"Channel {c} value {chan[0, 0]} is outside the expected "
                f"ImageNet-normalized range (<5)."
            )

    def test_float_zero_one_input_is_not_divided_again(self):
        """A float [0, 1] input must NOT be divided by 255 a second time.

        The pre-fix code would have been a no-op here (input_max<=1.0
        path), but we lock the new contract: float in [0,1] means
        "already normalized, do not scale".
        """
        preprocessor = UnifiedPreprocessor(model_id="scrfd")
        frame = _build_scrfd_zero_to_one_float_frame(16, 16)  # 0.5
        out = preprocessor._normalize(frame)

        # Expected = (0.5 - mean) / std, NOT ((0.5/255) - mean) / std
        expected = (0.5 - SCRFD_MEAN) / SCRFD_STD
        cy, cx = 8, 8
        np.testing.assert_allclose(
            out[cy, cx, :],
            expected,
            rtol=1e-5,
            atol=1e-6,
            err_msg=(
                "Float [0, 1] input was divided by 255 again — "
                "double normalization regression."
            ),
        )
        # Sanity: with /255 the values would all be ~-2.0, not ~0.2.
        assert abs(out[0, 0, 0]) < 1.0

    def test_output_dtype_and_shape_compatible_with_scrfd(self):
        """Output dtype / shape / layout must remain SCRFD-compatible."""
        preprocessor = UnifiedPreprocessor(model_id="scrfd")
        frame = _build_scrfd_uint8_frame(64, 64)
        out = preprocessor._normalize(frame)

        assert out.dtype == np.float32
        # _normalize returns HWC; downstream _to_chw will produce (3, 64, 64)
        # and the batched tensor is (1, 3, 64, 64).
        assert out.ndim == 3
        assert out.shape == (64, 64, 3)

    def test_black_and_white_endpoints_have_expected_magnitude(self):
        """Black (0) and white (255) uint8 inputs must produce values
        consistent with ImageNet normalization of [0,1], not the buggy
        pre-mean/std /255=0 /255=1 pre-mean/std outputs.

        Pre-fix: black  -> (0 - mean)/std     ≈ -2.12
                  white  -> (255 - mean)/std   ≈ 1109

        Post-fix: black -> (0   - mean)/std   ≈ -2.12
                  white -> (1.0 - mean)/std   ≈  2.64
        """
        preprocessor = UnifiedPreprocessor(model_id="scrfd")
        black = np.zeros((4, 4, 3), dtype=np.uint8)
        white = np.full((4, 4, 3), 255, dtype=np.uint8)

        out_black = preprocessor._normalize(black)
        out_white = preprocessor._normalize(white)

        expected_black = (0.0 - SCRFD_MEAN) / SCRFD_STD
        expected_white = (1.0 - SCRFD_MEAN) / SCRFD_STD

        np.testing.assert_allclose(out_black[0, 0, :], expected_black, rtol=1e-4, atol=1e-5)
        np.testing.assert_allclose(out_white[0, 0, :], expected_white, rtol=1e-4, atol=1e-5)

        # Explicit anti-regression: the white pixel must NOT be ~1100.
        assert np.all(np.abs(out_white) < 5.0), (
            f"White uint8 input produced out-of-range values "
            f"(min={out_white.min()}, max={out_white.max()}); "
            f"expected |x| < 5.0 — /255 was not applied."
        )

    def test_full_preprocess_pipeline_preserves_layout(self):
        """End-to-end preprocess() must still produce (1, 3, H, W) float32
        with H/W matching the SCRFD contract."""
        from app.data.frame import CanonicalFrame, FrameMetadata

        preprocessor = UnifiedPreprocessor(model_id="scrfd")
        contract = get_model_contract("scrfd").preprocessing

        bgr = np.full((128, 128, 3), 100, dtype=np.uint8)
        frame = CanonicalFrame(
            data=bgr,
            metadata=FrameMetadata(
                frame_index=0,
                source_id="test",
                timestamp=0.0,
            ),
        )

        result = preprocessor.preprocess(frame)

        expected_h, expected_w = contract.input_shape[1], contract.input_shape[2]
        assert result.tensor.shape == (1, 3, expected_h, expected_w)
        assert result.tensor.dtype == np.float32

        # The preprocessed tensor must also be in the expected magnitude
        # band (not ~500-scale).
        assert np.all(np.abs(result.tensor) < 5.0), (
            f"End-to-end SCRFD preprocess produced out-of-range values "
            f"(min={result.tensor.min()}, max={result.tensor.max()}); "
            f"the /255 bug has regressed."
        )

