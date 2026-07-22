"""
Shared file operations utilities (async-capable).
"""
import os
import shutil
from pathlib import Path
from typing import Optional, Union

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


def safe_replace(src: Union[str, Path], dest: Union[str, Path]) -> None:
    """
    Move src onto dest, removing an existing dest file first if needed.
    """
    src_path = Path(src)
    dest_path = Path(dest)
    try:
        os.makedirs(dest_path.parent, exist_ok=True)
        if dest_path.exists() and dest_path.resolve() != src_path.resolve():
            dest_path.unlink()
        shutil.move(str(src_path), str(dest_path))
    except Exception as exc:
        raise FileOperationError(f"Failed to replace {dest} with {src}", error=str(exc))


def archive_file(path: Union[str, Path], archive_dir: Union[str, Path]) -> Optional[str]:
    """
    Move a file into an archive directory. Returns archived path or None if missing.
    """
    src = Path(path)
    if not src.exists():
        return None
    try:
        dest_dir = Path(archive_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        # Avoid collisions
        if dest.exists():
            stem, suffix = src.stem, src.suffix
            idx = 1
            while dest.exists():
                dest = dest_dir / f"{stem}.old{idx}{suffix}"
                idx += 1
        shutil.move(str(src), str(dest))
        return str(dest)
    except Exception as exc:
        raise FileOperationError(f"Failed to archive file: {path}", error=str(exc))


def cleanup_old_files(
    root: Union[str, Path],
    older_than_days: int,
    *,
    recursive: bool = True,
) -> dict:
    """
    Delete files under root older than older_than_days.
    Returns counts of deleted files/bytes and any errors encountered.
    """
    import time

    root_path = Path(root)
    deleted_files = 0
    deleted_bytes = 0
    errors: list[str] = []

    if not root_path.exists():
        return {"deleted_files": 0, "deleted_bytes": 0, "errors": []}

    cutoff = time.time() - (older_than_days * 86400)
    iterator = root_path.rglob("*") if recursive else root_path.iterdir()

    for path in iterator:
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                size = path.stat().st_size
                path.unlink()
                deleted_files += 1
                deleted_bytes += size
        except OSError as exc:
            errors.append(f"{path}: {exc}")

    # Remove empty directories after file cleanup
    if recursive:
        for dirpath in sorted(root_path.rglob("*"), reverse=True):
            if dirpath.is_dir():
                try:
                    next(dirpath.iterdir())
                except StopIteration:
                    try:
                        dirpath.rmdir()
                    except OSError:
                        pass
                except OSError:
                    pass

    return {
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "errors": errors,
    }

