"""
Phase 44.X.4 R3.13-SCRFD-FIX — minimal real SCRFD inference smoke test.

Runs the existing SCRFD ONNX model through the fixed UnifiedPreprocessor
on a synthetic uint8 BGR frame and verifies:
  * preprocess produces a tensor with the correct shape/dtype
  * the preprocessed values are NOT in the ~500-scale garbage range
  * ONNX inference returns a valid output tensor (no NaN/Inf explosion)

Does NOT assert on detection quality (model is the real SCRFD but input
is a synthetic frame, not a real face), only on pipeline correctness.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data.preprocessing import UnifiedPreprocessor  # noqa: E402
from app.data.contracts import get_model_contract  # noqa: E402
from app.data.frame import CanonicalFrame, FrameMetadata  # noqa: E402


MODEL_PATH = ROOT / "models" / "scrfd" / "scrfd_10g_bnkps.onnx"


def main() -> int:
    if not MODEL_PATH.exists():
        print(f"SKIP: SCRFD model not found at {MODEL_PATH}")
        return 0

    preprocessor = UnifiedPreprocessor(model_id="scrfd")
    contract = get_model_contract("scrfd").preprocessing

    # Synthetic 1280x720 BGR frame, mid-gray
    h, w = 720, 1280
    bgr = np.full((h, w, 3), 128, dtype=np.uint8)
    frame = CanonicalFrame(
        data=bgr,
        metadata=FrameMetadata(frame_index=0, source_id="scrfd-smoke", timestamp=0.0),
    )

    result = preprocessor.preprocess(frame)
    tensor = result.tensor

    expected_h = contract.input_shape[1]
    expected_w = contract.input_shape[2]
    assert tensor.shape == (1, 3, expected_h, expected_w), tensor.shape
    assert tensor.dtype == np.float32, tensor.dtype
    assert np.all(np.isfinite(tensor)), "Preprocessed tensor contains non-finite values"
    assert np.all(np.abs(tensor) < 10.0), (
        f"Preprocessed tensor in ~500-scale garbage range: "
        f"min={tensor.min()}, max={tensor.max()}"
    )
    print(
        f"PREPROCESS OK  shape={tensor.shape} dtype={tensor.dtype} "
        f"min={tensor.min():.3f} max={tensor.max():.3f}"
    )

    # Now run actual ONNX inference on the preprocessed tensor.
    import onnxruntime as ort

    sess = ort.InferenceSession(
        str(MODEL_PATH),
        providers=["CPUExecutionProvider"],
    )
    input_name = sess.get_inputs()[0].name
    outputs = sess.run(None, {input_name: tensor})

    for i, out in enumerate(outputs):
        assert np.all(np.isfinite(out)), f"ONNX output {i} contains non-finite values"
        print(
            f"INFERENCE OK    output[{i}] shape={out.shape} "
            f"min={out.min():.4f} max={out.max():.4f} mean={out.mean():.4f}"
        )

    print("SMOKE TEST PASS — real SCRFD inference ran end-to-end with the fix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
