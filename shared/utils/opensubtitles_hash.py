"""
OpenSubtitles movie hash (first + last 64 KiB XOR with file size).
Used by OpenSubtitles.com search for release matching.
"""
from pathlib import Path
from typing import Union

from shared.exceptions.base import FileNotFoundError, FileOperationError


def opensubtitles_movie_hash(path: Union[str, Path]) -> str:
    """
    Compute the classic OpenSubtitles movie hash for a media file.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        size = file_path.stat().st_size
        hash_value = size

        with open(file_path, "rb") as handle:
            # First 64 KiB
            for _ in range(8192):
                buffer = handle.read(8)
                if len(buffer) < 8:
                    break
                hash_value += int.from_bytes(buffer, byteorder="little", signed=False)
                hash_value &= 0xFFFFFFFFFFFFFFFF

            # Last 64 KiB
            if size >= 65536:
                handle.seek(max(0, size - 65536))
                for _ in range(8192):
                    buffer = handle.read(8)
                    if len(buffer) < 8:
                        break
                    hash_value += int.from_bytes(buffer, byteorder="little", signed=False)
                    hash_value &= 0xFFFFFFFFFFFFFFFF

        return f"{hash_value:016x}"
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise FileOperationError(f"Failed to compute OpenSubtitles hash: {file_path}", error=str(exc))
