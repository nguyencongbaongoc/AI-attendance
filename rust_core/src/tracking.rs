use ndarray::{Array1, Array2};
use numpy::{IntoPyArray, PyArray1, PyArray2, PyReadonlyArray2};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Compute pixel-space (3840x2160) IoU matrix and greedy assignment in one FFI call with GIL released.
///
/// Returns: (iou_matrix (N, M), matches Vec<(track_idx, det_idx)>, unmatched_tracks, unmatched_dets)
#[pyfunction]
pub fn batch_iou_and_match_rs(
    py: Python<'_>,
    track_boxes: PyReadonlyArray2<'_, f32>,
    det_boxes: PyReadonlyArray2<'_, f32>,
    iou_thresh: f32,
) -> PyResult<(Py<PyArray2<f32>>, Vec<(usize, usize)>, Vec<usize>, Vec<usize>)> {
    let t_arr = track_boxes.as_array();
    let d_arr = det_boxes.as_array();

    if t_arr.ncols() != 4 && t_arr.nrows() > 0 {
        return Err(PyValueError::new_err("track_boxes must have shape (N, 4)"));
    }
    if d_arr.ncols() != 4 && d_arr.nrows() > 0 {
        return Err(PyValueError::new_err("det_boxes must have shape (M, 4)"));
    }

    let n = t_arr.nrows();
    let m = d_arr.nrows();

    let (iou_mat, matches, unmatched_tracks, unmatched_dets) = py.allow_threads(|| {
        let mut iou = Array2::<f32>::zeros((n, m));
        if n == 0 || m == 0 {
            let ut: Vec<usize> = (0..n).collect();
            let ud: Vec<usize> = (0..m).collect();
            return (iou, Vec::new(), ut, ud);
        }

        // Precompute box areas
        let mut t_areas = Vec::with_capacity(n);
        for i in 0..n {
            let w = (t_arr[[i, 2]] - t_arr[[i, 0]]).max(0.0);
            let h = (t_arr[[i, 3]] - t_arr[[i, 1]]).max(0.0);
            t_areas.push(w * h);
        }

        let mut d_areas = Vec::with_capacity(m);
        for j in 0..m {
            let w = (d_arr[[j, 2]] - d_arr[[j, 0]]).max(0.0);
            let h = (d_arr[[j, 3]] - d_arr[[j, 1]]).max(0.0);
            d_areas.push(w * h);
        }

        for i in 0..n {
            let tx1 = t_arr[[i, 0]];
            let ty1 = t_arr[[i, 1]];
            let tx2 = t_arr[[i, 2]];
            let ty2 = t_arr[[i, 3]];
            let ta = t_areas[i];

            for j in 0..m {
                let ix1 = tx1.max(d_arr[[j, 0]]);
                let iy1 = ty1.max(d_arr[[j, 1]]);
                let ix2 = tx2.min(d_arr[[j, 2]]);
                let iy2 = ty2.min(d_arr[[j, 3]]);

                let iw = (ix2 - ix1).max(0.0);
                let ih = (iy2 - iy1).max(0.0);
                let inter = iw * ih;

                if inter > 0.0 {
                    let union = ta + d_areas[j] - inter;
                    if union > 0.0 {
                        iou[[i, j]] = inter / union.max(1e-12);
                    }
                }
            }
        }

        // Greedy assignment ordered by track index
        let mut det_assigned = vec![false; m];
        let mut track_assigned = vec![false; n];
        let mut matches = Vec::with_capacity(n.min(m));

        for i in 0..n {
            let mut best_j: isize = -1;
            let mut best_iou: f32 = iou_thresh;

            for j in 0..m {
                if det_assigned[j] {
                    continue;
                }
                let val = iou[[i, j]];
                if val >= iou_thresh && (best_j == -1 || val > best_iou) {
                    best_iou = val;
                    best_j = j as isize;
                }
            }

            if best_j >= 0 {
                let j_idx = best_j as usize;
                det_assigned[j_idx] = true;
                track_assigned[i] = true;
                matches.push((i, j_idx));
            }
        }

        let unmatched_tracks: Vec<usize> = (0..n).filter(|&i| !track_assigned[i]).collect();
        let unmatched_dets: Vec<usize> = (0..m).filter(|&j| !det_assigned[j]).collect();

        (iou, matches, unmatched_tracks, unmatched_dets)
    });

    Ok((
        iou_mat.into_pyarray_bound(py).unbind(),
        matches,
        unmatched_tracks,
        unmatched_dets,
    ))
}

/// Vector cross-product segment intersection returning 1 (IN), -1 (OUT), or 0 (NONE) for all tracks.
#[pyfunction]
pub fn batch_line_crossing_rs(
    py: Python<'_>,
    prev_pts: PyReadonlyArray2<'_, f32>,
    curr_pts: PyReadonlyArray2<'_, f32>,
    line_p1: (f32, f32),
    line_p2: (f32, f32),
) -> PyResult<Py<PyArray1<i8>>> {
    let p_arr = prev_pts.as_array();
    let c_arr = curr_pts.as_array();

    if p_arr.nrows() != c_arr.nrows() {
        return Err(PyValueError::new_err(
            "prev_pts and curr_pts must have the same number of rows",
        ));
    }
    if p_arr.nrows() > 0 && (p_arr.ncols() != 2 || c_arr.ncols() != 2) {
        return Err(PyValueError::new_err(
            "prev_pts and curr_pts must have shape (K, 2)",
        ));
    }

    let k = p_arr.nrows();
    let (lx1, ly1) = line_p1;
    let (lx2, ly2) = line_p2;
    let ldx = lx2 - lx1;
    let ldy = ly2 - ly1;

    let out = py.allow_threads(|| {
        let mut res = Array1::<i8>::zeros(k);
        for i in 0..k {
            let px = p_arr[[i, 0]];
            let py_ = p_arr[[i, 1]];
            let cx = c_arr[[i, 0]];
            let cy = c_arr[[i, 1]];

            let cross_prev = ldx * (py_ - ly1) - ldy * (px - lx1);
            let cross_curr = ldx * (cy - ly1) - ldy * (cx - lx1);

            if cross_prev * cross_curr < 0.0 {
                // Segment straddle check on (prev -> curr) vs (line_p1 -> line_p2)
                let tdx = cx - px;
                let tdy = cy - py_;
                let d1 = tdx * (ly1 - py_) - tdy * (lx1 - px);
                let d2 = tdx * (ly2 - py_) - tdy * (lx2 - px);
                if d1 * d2 <= 0.0 {
                    res[i] = if cross_prev > 0.0 { 1 } else { -1 };
                }
            }
        }
        res
    });

    Ok(out.into_pyarray_bound(py).unbind())
}
