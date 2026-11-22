use std::sync::RwLock;

use ndarray::Array2;
use numpy::{PyReadonlyArray1, PyReadonlyArray2};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

/// Pure Rust Non-Maximum Suppression returning kept indices sorted by descending score.
#[pyfunction]
pub fn fast_nms_rs(
    py: Python<'_>,
    boxes: PyReadonlyArray2<'_, f32>,
    scores: PyReadonlyArray1<'_, f32>,
    iou_thresh: f32,
) -> PyResult<Vec<usize>> {
    let b_arr = boxes.as_array();
    let s_arr = scores.as_array();
    let n = b_arr.nrows();

    if n != s_arr.len() {
        return Err(PyValueError::new_err(
            "boxes and scores must have the same length",
        ));
    }
    if n > 0 && b_arr.ncols() != 4 {
        return Err(PyValueError::new_err("boxes must have shape (N, 4)"));
    }

    let kept = py.allow_threads(|| {
        if n == 0 {
            return Vec::new();
        }

        let mut order: Vec<usize> = (0..n).collect();
        order.sort_unstable_by(|&a, &b| {
            s_arr[b]
                .partial_cmp(&s_arr[a])
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut areas = Vec::with_capacity(n);
        for i in 0..n {
            let w = (b_arr[[i, 2]] - b_arr[[i, 0]]).max(0.0);
            let h = (b_arr[[i, 3]] - b_arr[[i, 1]]).max(0.0);
            areas.push(w * h);
        }

        let mut suppressed = vec![false; n];
        let mut keep = Vec::with_capacity(n);

        for pos in 0..n {
            let i = order[pos];
            if suppressed[i] {
                continue;
            }
            keep.push(i);

            let x1 = b_arr[[i, 0]];
            let y1 = b_arr[[i, 1]];
            let x2 = b_arr[[i, 2]];
            let y2 = b_arr[[i, 3]];
            let area_i = areas[i];

            for pos2 in (pos + 1)..n {
                let j = order[pos2];
                if suppressed[j] {
                    continue;
                }
                let ix1 = x1.max(b_arr[[j, 0]]);
                let iy1 = y1.max(b_arr[[j, 1]]);
                let ix2 = x2.min(b_arr[[j, 2]]);
                let iy2 = y2.min(b_arr[[j, 3]]);

                let iw = (ix2 - ix1).max(0.0);
                let ih = (iy2 - iy1).max(0.0);
                let inter = iw * ih;
                if inter > 0.0 {
                    let union = area_i + areas[j] - inter;
                    let iou = if union > 0.0 { inter / union } else { 0.0 };
                    if iou > iou_thresh {
                        suppressed[j] = true;
                    }
                }
            }
        }
        keep
    });

    Ok(kept)
}

struct GalleryData {
    embeddings: Array2<f32>, // (N, 512), L2-normalized rows
}

/// Thread-safe RwLock-protected 512D ArcFace gallery index for atomic hot-reload and GIL-released search.
#[pyclass(module = "attendance_core")]
pub struct GalleryIndexRs {
    inner: RwLock<GalleryData>,
}

#[pymethods]
impl GalleryIndexRs {
    #[new]
    pub fn new() -> Self {
        Self {
            inner: RwLock::new(GalleryData {
                embeddings: Array2::<f32>::zeros((0, 512)),
            }),
        }
    }

    /// Atomically replace the (N, 512) gallery matrix with L2-normalized embeddings.
    pub fn update_gallery(&self, py: Python<'_>, embeddings: PyReadonlyArray2<'_, f32>) -> PyResult<usize> {
        let arr = embeddings.as_array();
        let n = arr.nrows();
        let d = arr.ncols();
        if n > 0 && d != 512 {
            return Err(PyValueError::new_err(format!(
                "Expected embeddings shape (N, 512), got ({n}, {d})"
            )));
        }

        let normalized = py.allow_threads(|| {
            let mut mat = if n == 0 {
                Array2::<f32>::zeros((0, 512))
            } else {
                arr.to_owned()
            };
            for mut row in mat.rows_mut() {
                let sq: f32 = row.iter().map(|&v| v * v).sum();
                let norm = sq.sqrt();
                if norm > 1e-12 {
                    let inv = 1.0 / norm;
                    for v in row.iter_mut() {
                        *v *= inv;
                    }
                }
            }
            mat
        });

        let mut guard = self.inner.write().map_err(|_| {
            PyValueError::new_err("GalleryIndexRs write lock poisoned")
        })?;
        guard.embeddings = normalized;
        Ok(n)
    }

    /// Search top-1 cosine similarity match with GIL released.
    /// Returns (best_index, best_similarity); (-1, best_similarity_or_0) if below threshold or empty.
    pub fn search_top1(
        &self,
        py: Python<'_>,
        query: PyReadonlyArray1<'_, f32>,
        threshold: f32,
    ) -> PyResult<(isize, f32)> {
        let q_arr = query.as_array();
        if q_arr.len() != 512 {
            return Err(PyValueError::new_err(format!(
                "Expected query embedding of length 512, got {}",
                q_arr.len()
            )));
        }

        // Copy & normalize query on stack before releasing GIL
        let mut q_norm = [0.0f32; 512];
        let mut sq = 0.0f32;
        for i in 0..512 {
            let v = q_arr[i];
            q_norm[i] = v;
            sq += v * v;
        }
        let norm = sq.sqrt();
        if norm > 1e-12 {
            let inv = 1.0 / norm;
            for v in q_norm.iter_mut() {
                *v *= inv;
            }
        }

        let (best_idx, best_sim) = py.allow_threads(|| {
            let guard = self.inner.read().expect("GalleryIndexRs read lock poisoned");
            let n = guard.embeddings.nrows();
            if n == 0 {
                return (-1isize, 0.0f32);
            }

            if n >= 64 {
                let (idx, sim) = (0..n)
                    .into_par_iter()
                    .map(|i| {
                        let row = guard.embeddings.row(i);
                        let mut dot = 0.0f32;
                        if let Some(slice) = row.as_slice() {
                            for k in 0..512 {
                                dot += slice[k] * q_norm[k];
                            }
                        } else {
                            for (k, &v) in row.iter().enumerate() {
                                dot += v * q_norm[k];
                            }
                        }
                        (i as isize, dot)
                    })
                    .reduce(
                        || (-1isize, f32::NEG_INFINITY),
                        |a, b| if b.1 > a.1 { b } else { a },
                    );
                (idx, sim)
            } else {
                let mut best_i: isize = -1;
                let mut best_s = f32::NEG_INFINITY;
                for i in 0..n {
                    let row = guard.embeddings.row(i);
                    let mut dot = 0.0f32;
                    if let Some(slice) = row.as_slice() {
                        for k in 0..512 {
                            dot += slice[k] * q_norm[k];
                        }
                    } else {
                        for (k, &v) in row.iter().enumerate() {
                            dot += v * q_norm[k];
                        }
                    }
                    if dot > best_s {
                        best_s = dot;
                        best_i = i as isize;
                    }
                }
                (best_i, best_s)
            }
        });

        if best_idx >= 0 && best_sim >= threshold {
            Ok((best_idx, best_sim))
        } else {
            Ok((-1, if best_idx >= 0 { best_sim } else { 0.0 }))
        }
    }

    pub fn len(&self) -> PyResult<usize> {
        let guard = self.inner.read().map_err(|_| {
            PyValueError::new_err("GalleryIndexRs read lock poisoned")
        })?;
        Ok(guard.embeddings.nrows())
    }
}
