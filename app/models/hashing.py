"""
Model file hashing for Windows native AI attendance system.

Provides SHA256 hash computation and verification for model files.

This module does NOT perform inference.
This module does NOT modify model files.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from app.models.contracts import HashStatus


# Buffer size for reading files (64KB)
HASH_BUFFER_SIZE = 65536


@dataclass
class HashResult:
    """
    Result of a hash computation or verification.
    
    Attributes:
        status: The hash verification status.
        expected_hash: The expected SHA256 hash (if provided).
        actual_hash: The actual computed SHA256 hash (if file exists).
        file_path: Path to the file that was hashed.
        file_size: Size of the file in bytes (if file exists).
        error: Error message if an error occurred.
    """
    
    status: HashStatus
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    error: Optional[str] = None
    
    def is_verified(self) -> bool:
        """Check if the hash was verified successfully."""
        return self.status == HashStatus.VERIFIED
    
    def is_missing(self) -> bool:
        """Check if the file is missing."""
        return self.status == HashStatus.MISSING
    
    def is_mismatch(self) -> bool:
        """Check if there was a hash mismatch."""
        return self.status == HashStatus.HASH_MISMATCH
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "status": self.status.value,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "error": self.error,
        }


def compute_sha256(file_path: Union[str, Path]) -> str:
    """
    Compute SHA256 hash of a file.
    
    Args:
        file_path: Path to the file to hash.
        
    Returns:
        Hexadecimal SHA256 hash string.
        
    Raises:
        FileNotFoundError: If the file does not exist.
        IOError: If the file cannot be read.
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    if not path.is_file():
        raise IOError(f"Path is not a file: {path}")
    
    sha256_hash = hashlib.sha256()
    
    with open(path, "rb") as f:
        # Read file in chunks to handle large files
        while True:
            data = f.read(HASH_BUFFER_SIZE)
            if not data:
                break
            sha256_hash.update(data)
    
    return sha256_hash.hexdigest()


def verify_sha256(
    file_path: Union[str, Path],
    expected_hash: Optional[str] = None,
) -> HashResult:
    """
    Verify SHA256 hash of a file.
    
    Args:
        file_path: Path to the file to verify.
        expected_hash: Expected SHA256 hash. If None, only computes the hash
                       without verification.
        
    Returns:
        HashResult with verification status and details.
    """
    path = Path(file_path)
    
    # Check if file exists
    if not path.exists():
        return HashResult(
            status=HashStatus.MISSING,
            expected_hash=expected_hash,
            file_path=str(path),
        )
    
    if not path.is_file():
        return HashResult(
            status=HashStatus.MISSING,
            expected_hash=expected_hash,
            file_path=str(path),
            error="Path is not a file",
        )
    
    try:
        # Compute actual hash
        actual_hash = compute_sha256(path)
        file_size = path.stat().st_size
        
        # If no expected hash, we can't verify
        if expected_hash is None:
            return HashResult(
                status=HashStatus.NO_EXPECTED_HASH,
                actual_hash=actual_hash,
                file_path=str(path),
                file_size=file_size,
            )
        
        # Compare hashes (case-insensitive)
        if actual_hash.lower() == expected_hash.lower():
            return HashResult(
                status=HashStatus.VERIFIED,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
                file_path=str(path),
                file_size=file_size,
            )
        else:
            return HashResult(
                status=HashStatus.HASH_MISMATCH,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
                file_path=str(path),
                file_size=file_size,
            )
    
    except Exception as e:
        return HashResult(
            status=HashStatus.NOT_VERIFIED,
            expected_hash=expected_hash,
            file_path=str(path),
            error=str(e),
        )


def compute_file_size(file_path: Union[str, Path]) -> Optional[int]:
    """
    Get the size of a file in bytes.
    
    Args:
        file_path: Path to the file.
        
    Returns:
        File size in bytes, or None if file doesn't exist.
    """
    path = Path(file_path)
    
    if not path.exists() or not path.is_file():
        return None
    
    return path.stat().st_size