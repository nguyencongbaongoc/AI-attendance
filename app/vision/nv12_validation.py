def validate_nv12_frame(width: int = 3840, height: int = 2160) -> bool:
    """Lightweight NV12 metadata validation."""
    import torch
    if width != 3840 or height != 2160:
        return False
    # If a tensor is passed, check basic properties
    return True

def validate_nv12_planes(y_plane, uv_plane) -> dict:
    import torch
    result = {"valid": True, "errors": []}
    try:
        if y_plane is None or uv_plane is None:
            result["valid"] = False
            result["errors"].append("missing_plane")
            return result
        if not hasattr(y_plane, 'shape'):
            result["valid"] = False
            result["errors"].append("y_plane_no_shape")
        else:
            if y_plane.shape[0] != 2160 or y_plane.shape[1] != 3840:
                result["errors"].append(f"y_shape_wrong:{y_plane.shape}")
        if not hasattr(uv_plane, 'shape'):
            result["errors"].append("uv_plane_no_shape")
        else:
            expected_uv_shape = (1080, 1920, 2)
            if uv_plane.shape != expected_uv_shape:
                result["errors"].append(f"uv_shape_wrong:{uv_plane.shape}")
        # Check CUDA device consistency if tensor
        if hasattr(y_plane, 'device'):
            device_str = str(y_plane.device)
            if 'cuda' not in device_str:
                result["errors"].append(f"y_not_cuda:{device_str}")
        if result["errors"]:
            result["valid"] = False
    except Exception as e:
        result["valid"] = False
        result["errors"].append(str(e))
    return result
