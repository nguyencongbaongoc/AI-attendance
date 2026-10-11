"""
Excel Student Roster Import Service.

Parses .xlsx/.csv files and validates/upserts student records.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from app.models.student import (
    Student,
    Class,
    EnrollmentStatusEnum,
    get_or_create_class,
    upsert_student,
)


# Column name mappings (support Vietnamese headers)
REQUIRED_COLUMNS = {
    "student_id": ["student_id", "ma_hoc_sinh", "mã học sinh", "ma hoc sinh"],
    "full_name": ["full_name", "ho_va_ten", "họ và tên", "ho va ten"],
    "class_name": ["class_name", "lop", "lớp", "class"],
}

OPTIONAL_COLUMNS = {
    "date_of_birth": ["date_of_birth", "ngay_sinh", "ngày sinh", "dob"],
    "gender": ["gender", "gioi_tinh", "giới tính"],
    "parent_phone": ["parent_phone", "sdt_phu_huynh", "số điện thoại phụ huynh", "phone"],
}


@dataclass
class ValidationError:
    """Validation error for a row."""
    row_number: int
    column: str
    value: str
    message: str


@dataclass
class ImportResult:
    """Result of import operation."""
    imported: int = 0
    updated: int = 0
    errors: list[ValidationError] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def normalize_header(header: str) -> str:
    """Normalize header string for comparison."""
    # NFC normalization for Vietnamese characters
    normalized = unicodedata.normalize("NFC", header.strip().lower())
    # Replace spaces and special chars
    normalized = normalized.replace(" ", "_").replace("-", "_")
    return normalized


def detect_columns(headers: list[str]) -> dict[str, int]:
    """
    Detect column indices from header row.
    
    Args:
        headers: List of header strings
        
    Returns:
        Dict mapping internal column name to column index (0-based)
    """
    normalized_headers = [normalize_header(h) for h in headers]
    column_map = {}
    
    # Find required columns
    for internal_name, possible_names in REQUIRED_COLUMNS.items():
        found = False
        for possible in possible_names:
            norm_possible = normalize_header(possible)
            if norm_possible in normalized_headers:
                column_map[internal_name] = normalized_headers.index(norm_possible)
                found = True
                break
        if not found:
            raise ValueError(f"Required column '{internal_name}' not found. Expected one of: {possible_names}")
    
    # Find optional columns
    for internal_name, possible_names in OPTIONAL_COLUMNS.items():
        for possible in possible_names:
            norm_possible = normalize_header(possible)
            if norm_possible in normalized_headers:
                column_map[internal_name] = normalized_headers.index(norm_possible)
                break
    
    return column_map


def parse_date(value: str) -> Optional[date]:
    """Parse date from various formats."""
    if not value or not str(value).strip():
        return None
    
    value = str(value).strip()
    # Try common formats
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%m/%d/%Y",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    
    # Try Excel serial date (if numeric)
    try:
        serial = float(value)
        # Excel epoch is 1899-12-30
        base_date = date(1899, 12, 30)
        return base_date + datetime.timedelta(days=int(serial))
    except (ValueError, OverflowError):
        pass
    
    return None


def normalize_gender(value: str) -> str:
    """Normalize gender value."""
    if not value:
        return "OTHER"
    
    value = str(value).strip().lower()
    
    male_values = {"male", "m", "nam", "nam giới", "boy"}
    female_values = {"female", "f", "nu", "nữ", "nữ giới", "girl"}
    
    if value in male_values:
        return "MALE"
    elif value in female_values:
        return "FEMALE"
    else:
        return "OTHER"


def normalize_phone(value: str) -> Optional[str]:
    """Normalize phone number."""
    if not value:
        return None
    
    value = str(value).strip()
    # Remove non-digits
    digits = "".join(c for c in value if c.isdigit())
    
    # Validate length (Vietnam phone numbers)
    if len(digits) >= 10 and len(digits) <= 11:
        return digits
    
    return value  # Return as-is if can't normalize


def sanitize_student_id(value: str) -> str:
    """Sanitize student_id for safe filename."""
    if not value:
        return ""
    
    # Remove invalid filename characters
    value = str(value).strip()
    # Keep alphanumeric, underscore, hyphen
    import re
    value = re.sub(r"[^a-zA-Z0-9_\-]", "", value)
    return value


def validate_student_id(value: str) -> Optional[ValidationError]:
    """Validate student_id."""
    if not value or not value.strip():
        return ValidationError(0, "student_id", value, "student_id is required")
    
    sanitized = sanitize_student_id(value)
    if sanitized != value:
        return ValidationError(0, "student_id", value, "student_id contains invalid characters")
    
    if len(sanitized) > 32:
        return ValidationError(0, "student_id", value, "student_id too long (max 32 chars)")
    
    return None


async def import_students_from_excel(
    session,
    file_path: str,
) -> ImportResult:
    """
    Import students from Excel file.
    
    Args:
        session: Database session
        file_path: Path to .xlsx file
        
    Returns:
        ImportResult with counts and errors
    """
    result = ImportResult()
    path = Path(file_path)
    
    if not path.exists():
        result.errors.append(ValidationError(0, "file", file_path, "File not found"))
        return result
    
    if path.suffix.lower() not in (".xlsx", ".xls", ".csv"):
        result.errors.append(ValidationError(0, "file", file_path, "Unsupported format. Use .xlsx or .csv"))
        return result
    
    try:
        if path.suffix.lower() == ".csv":
            return await _import_from_csv(session, file_path, result)
        else:
            return await _import_from_excel(session, file_path, result)
    except Exception as e:
        result.errors.append(ValidationError(0, "file", file_path, f"Import failed: {str(e)}"))
        return result


async def _import_from_excel(
    session,
    file_path: str,
    result: ImportResult,
) -> ImportResult:
    """Import from .xlsx file."""
    workbook = openpyxl.load_workbook(file_path, data_only=True)
    sheet = workbook.active
    
    if sheet is None:
        result.errors.append(ValidationError(0, "file", file_path, "No active sheet"))
        return result
    
    # Get headers from first row
    headers = []
    for cell in sheet[1]:
        headers.append(str(cell.value) if cell.value else "")
    
    # Detect columns
    try:
        column_map = detect_columns(headers)
    except ValueError as e:
        result.errors.append(ValidationError(0, "header", "", str(e)))
        return result
    
    # Process data rows
    for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        # Skip empty rows
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        
        # Extract values
        student_id = str(row[column_map["student_id"]]).strip() if row[column_map["student_id"]] else ""
        full_name = str(row[column_map["full_name"]]).strip() if row[column_map["full_name"]] else ""
        class_name = str(row[column_map["class_name"]]).strip() if row[column_map["class_name"]] else ""
        
        # Validate required fields
        if not student_id:
            result.errors.append(ValidationError(row_idx, "student_id", "", "student_id is required"))
            continue
        
        if not full_name:
            result.errors.append(ValidationError(row_idx, "full_name", "", "full_name is required"))
            continue
        
        if not class_name:
            result.errors.append(ValidationError(row_idx, "class_name", "", "class_name is required"))
            continue
        
        # Validate student_id
        id_error = validate_student_id(student_id)
        if id_error:
            id_error.row_number = row_idx
            result.errors.append(id_error)
            continue
        
        student_id = sanitize_student_id(student_id)
        
        # Parse optional fields
        date_of_birth = None
        if "date_of_birth" in column_map:
            date_of_birth = parse_date(row[column_map["date_of_birth"]])
        
        gender = "OTHER"
        if "gender" in column_map:
            gender = normalize_gender(row[column_map["gender"]])
        
        parent_phone = None
        if "parent_phone" in column_map:
            parent_phone = normalize_phone(row[column_map["parent_phone"]])
        
        # Get or create class
        try:
            class_obj = await get_or_create_class(session, class_name, class_name)
        except Exception as e:
            result.errors.append(ValidationError(row_idx, "class_name", class_name, f"Class error: {str(e)}"))
            continue
        
        # Upsert student
        # Check if embedding file already exists for this student_id
        embeddings_dir = Path("app/data/embeddings")
        embedding_path = embeddings_dir / f"{student_id}.npy"
        has_embedding = embedding_path.exists()
        
        embedding_path_str = str(embedding_path) if has_embedding else None
        enrollment_status = EnrollmentStatusEnum.ENROLLED if has_embedding else EnrollmentStatusEnum.PENDING
        
        try:
            student = await upsert_student(
                session=session,
                student_id=student_id,
                full_name=full_name,
                class_id=class_obj.class_id,
                date_of_birth=date_of_birth,
                gender=gender,
                parent_phone=parent_phone,
                embedding_path=embedding_path_str,
            )
            
            # Update enrollment status if embedding exists
            if has_embedding:
                student.enrollment_status = enrollment_status
            
            # Check if this was an insert or update
            if student.created_at == student.updated_at:
                result.imported += 1
            else:
                result.updated += 1
                
        except Exception as e:
            result.errors.append(ValidationError(row_idx, "database", student_id, f"Upsert failed: {str(e)}"))
    
    return result


async def _import_from_csv(
    session,
    file_path: str,
    result: ImportResult,
) -> ImportResult:
    """Import from .csv file."""
    import csv
    
    with open(file_path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)
    
    if not rows:
        result.errors.append(ValidationError(0, "file", file_path, "Empty file"))
        return result
    
    headers = rows[0]
    
    try:
        column_map = detect_columns(headers)
    except ValueError as e:
        result.errors.append(ValidationError(0, "header", "", str(e)))
        return result
    
    for row_idx, row in enumerate(rows[1:], start=2):
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue
        
        # Pad row if shorter than headers
        while len(row) < len(headers):
            row.append("")
        
        student_id = str(row[column_map["student_id"]]).strip() if row[column_map["student_id"]] else ""
        full_name = str(row[column_map["full_name"]]).strip() if row[column_map["full_name"]] else ""
        class_name = str(row[column_map["class_name"]]).strip() if row[column_map["class_name"]] else ""
        
        if not student_id:
            result.errors.append(ValidationError(row_idx, "student_id", "", "student_id is required"))
            continue
        
        if not full_name:
            result.errors.append(ValidationError(row_idx, "full_name", "", "full_name is required"))
            continue
        
        if not class_name:
            result.errors.append(ValidationError(row_idx, "class_name", "", "class_name is required"))
            continue
        
        id_error = validate_student_id(student_id)
        if id_error:
            id_error.row_number = row_idx
            result.errors.append(id_error)
            continue
        
        student_id = sanitize_student_id(student_id)
        
        date_of_birth = None
        if "date_of_birth" in column_map:
            date_of_birth = parse_date(row[column_map["date_of_birth"]])
        
        gender = "OTHER"
        if "gender" in column_map:
            gender = normalize_gender(row[column_map["gender"]])
        
        parent_phone = None
        if "parent_phone" in column_map:
            parent_phone = normalize_phone(row[column_map["parent_phone"]])
        
        try:
            class_obj = await get_or_create_class(session, class_name, class_name)
        except Exception as e:
            result.errors.append(ValidationError(row_idx, "class_name", class_name, f"Class error: {str(e)}"))
            continue
        
        # Check if embedding file already exists for this student_id
        embeddings_dir = Path("app/data/embeddings")
        embedding_path = embeddings_dir / f"{student_id}.npy"
        has_embedding = embedding_path.exists()
        
        embedding_path_str = str(embedding_path) if has_embedding else None
        enrollment_status = EnrollmentStatusEnum.ENROLLED if has_embedding else EnrollmentStatusEnum.PENDING
        
        try:
            student = await upsert_student(
                session=session,
                student_id=student_id,
                full_name=full_name,
                class_id=class_obj.class_id,
                date_of_birth=date_of_birth,
                gender=gender,
                parent_phone=parent_phone,
                embedding_path=embedding_path_str,
            )
            
            # Update enrollment status if embedding exists
            if has_embedding:
                student.enrollment_status = enrollment_status
            
            if student.created_at == student.updated_at:
                result.imported += 1
            else:
                result.updated += 1
                
        except Exception as e:
            result.errors.append(ValidationError(row_idx, "database", student_id, f"Upsert failed: {str(e)}"))
    
    return result


def create_sample_excel(output_path: str) -> None:
    """Create a sample Excel file for testing."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Students"
    
    # Headers (Vietnamese)
    headers = ["Mã học sinh", "Họ và tên", "Lớp", "Ngày sinh", "Giới tính", "Số điện thoại phụ huynh"]
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = openpyxl.styles.Font(bold=True)
    
    # Sample data
    sample_data = [
        ["HS2026_10A1_01", "Nguyễn Văn An", "10A1", "2008-05-15", "Nam", "0901234567"],
        ["HS2026_10A1_02", "Trần Thị Bích", "10A1", "2008-08-22", "Nữ", "0912345678"],
        ["HS2026_10A2_01", "Lê Hoàng Long", "10A2", "2008-03-10", "Nam", "0923456789"],
    ]
    
    for row_idx, data in enumerate(sample_data, 2):
        for col_idx, value in enumerate(data, 1):
            ws.cell(row=row_idx, column=col_idx, value=value)
    
    # Auto-adjust column widths
    for col in ws.columns:
        max_length = 0
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max(max_length + 2, 12), 30)
        ws.column_dimensions[col[0].column_letter].width = adjusted_width
    
    wb.save(output_path)
    print(f"Sample Excel created at {output_path}")