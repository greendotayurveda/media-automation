"""
Hashing utilities to verify file integrity.
"""
import hashlib
from pathlib import Path
from typing import Union

from shared.exceptions.base import FileNotFoundError, FileOperationError


def calculate_file_hash(path: Union[str, Path], algorithm: str = "sha256", chunk_size: int = 65536) -> str:
    """
    Calculate the hash (MD5, SHA256) of a file in chunks to prevent memory overhead
    with large media files.
    """
    if not Path(path).exists():
        raise FileNotFoundError(f"File not found: {path}")

    try:
        hash_func = hashlib.new(algorithm)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hash_func.update(chunk)
        return hash_func.hexdigest()
    except Exception as exc:
        raise FileOperationError(f"Failed to calculate file hash: {path}", error=str(exc))
