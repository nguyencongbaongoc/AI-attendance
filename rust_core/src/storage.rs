use std::path::Path;
use std::time::{Duration, SystemTime};

use pyo3::prelude::*;
use rayon::prelude::*;
use walkdir::WalkDir;

/// Parallel walkdir + rayon directory scanner for RetentionService / DiskWatchdog.
/// Returns (expired_file_paths, total_bytes).
#[pyfunction]
pub fn scan_expired_files_rs(
    py: Python<'_>,
    root_dir: &str,
    max_age_secs: f64,
) -> PyResult<(Vec<String>, u64)> {
    let root = root_dir.to_string();
    let max_age = Duration::from_secs_f64(max_age_secs.max(0.0));

    let (paths, total_bytes) = py.allow_threads(|| {
        if !Path::new(&root).exists() {
            return (Vec::new(), 0u64);
        }

        let now = SystemTime::now();
        let results: Vec<(String, u64)> = WalkDir::new(&root)
            .into_iter()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_type().is_file())
            .par_bridge()
            .filter_map(|entry| {
                let meta = entry.metadata().ok()?;
                let modified = meta.modified().ok()?;
                let age = now.duration_since(modified).unwrap_or(Duration::ZERO);
                if age >= max_age {
                    let size = meta.len();
                    let p = entry.path().to_string_lossy().into_owned();
                    Some((p, size))
                } else {
                    None
                }
            })
            .collect();

        let mut total: u64 = 0;
        let mut out_paths = Vec::with_capacity(results.len());
        for (p, sz) in results {
            total = total.saturating_add(sz);
            out_paths.push(p);
        }
        (out_paths, total)
    });

    Ok((paths, total_bytes))
}
