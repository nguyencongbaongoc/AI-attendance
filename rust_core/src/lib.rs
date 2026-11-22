pub mod storage;
pub mod tracking;
pub mod vision;

use pyo3::prelude::*;

#[pymodule]
fn attendance_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(tracking::batch_iou_and_match_rs, m)?)?;
    m.add_function(wrap_pyfunction!(tracking::batch_line_crossing_rs, m)?)?;
    m.add_function(wrap_pyfunction!(vision::fast_nms_rs, m)?)?;
    m.add_class::<vision::GalleryIndexRs>()?;
    m.add_function(wrap_pyfunction!(storage::scan_expired_files_rs, m)?)?;
    Ok(())
}
