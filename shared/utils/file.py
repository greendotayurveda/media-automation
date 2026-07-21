"""
Shared file operations utilities (async-capable).
"""
import os
import shutil
from pathlib import Path
from typing import Union

import aiofiles

from shared.exceptions.base import FileNotFoundError, FileOperationError


async def read_file_async(path: Union[str, Path]) -> str:
    """Read file content asynchronously."""
    try:
        async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
            return await f.read()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"File not found: {path}") from exc
    except Exception as exc:
        raise FileOperationError(f"Failed to read file: {path}", error=str(exc))


async def write_file_async(path: Union[str, Path], content: str) -> None:
    """Write file content asynchronously."""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(path, mode="w", encoding="utf-8") as f:
            await f.write(content)
    except Exception as exc:
        raise FileOperationError(f"Failed to write file: {path}", error=str(exc))


def get_directory_size(path: Union[str, Path]) -> int:
    """Get total directory size in bytes recursively."""
    total_size = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                # skip symbolic links
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
    except Exception as exc:
        raise FileOperationError(f"Failed to calculate directory size: {path}", error=str(exc))
    return total_size


def safe_move(src: Union[str, Path], dest: Union[str, Path]) -> None:
    """Safely move a file, ensuring destination directory exists."""
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(str(src), str(dest))
    except Exception as exc:
        raise FileOperationError(f"Failed to move file from {src} to {dest}", error=str(exc))
