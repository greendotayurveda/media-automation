"""
Batch Library Video Compressor Script.
Scans library_root (/opt/media-platform/data/library) for existing video files,
evaluates eligibility, compresses H.264/MPEG2 videos to HEVC, and logs total storage saved.
"""
import asyncio
import time
from pathlib import Path

from shared.config.settings import settings
from shared.logging.logger import get_logger
from app.compressor import MediaCompressor

logger = get_logger("compress-library")

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".ts"}


async def main():
    library_root = settings.library_root
    print(f"🔍 Scanning library directory for video files: {library_root}")

    if not library_root.exists():
        print(f"❌ Library root path does not exist: {library_root}")
        return

    # Find all video files recursively in library
    files = [
        p for p in library_root.rglob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS and not p.name.startswith(".")
    ]

    if not files:
        print("ℹ️ No video files found in library directory.")
        return

    print(f"🎬 Found {len(files)} total video files in library.")
    print("--------------------------------------------------")

    compressor = MediaCompressor()

    total_orig_bytes = 0
    total_comp_bytes = 0
    total_savings_bytes = 0
    compressed_count = 0
    skipped_count = 0
    start_all = time.monotonic()

    for idx, file_path in enumerate(files, 1):
        print(f"\n[{idx}/{len(files)}] Evaluating: {file_path.name}")
        try:
            result = await compressor.compress(str(file_path))
            action = result.get("action")

            if action == "compressed":
                compressed_count += 1
                orig = result.get("original_size_bytes", 0)
                comp = result.get("compressed_size_bytes", 0)
                savings = result.get("savings_bytes", 0)
                pct = result.get("savings_percent", 0.0)

                total_orig_bytes += orig
                total_comp_bytes += comp
                total_savings_bytes += savings

                orig_gb = orig / (1024 ** 3)
                comp_gb = comp / (1024 ** 3)
                savings_gb = savings / (1024 ** 3)

                print(f"  ✅ Compressed successfully! {orig_gb:.2f} GB ➔ {comp_gb:.2f} GB (Saved {savings_gb:.2f} GB / {pct}%)")

            else:
                skipped_count += 1
                reason = result.get("reason", "unknown")
                print(f"  ⏭️ Skipped: {reason}")

        except Exception as exc:
            skipped_count += 1
            print(f"  ❌ Failed to compress: {exc}")

    elapsed_min = round((time.monotonic() - start_all) / 60, 2)
    saved_gb = round(total_savings_bytes / (1024 ** 3), 2)

    print("\n==================================================")
    print("🎉 BATCH LIBRARY COMPRESSION COMPLETED!")
    print(f"⏱️ Total Duration: {elapsed_min} minutes")
    print(f"📊 Movies Compressed: {compressed_count} | Skipped: {skipped_count}")
    print(f"💾 Total Storage Reclaimed: {saved_gb} GB")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(main())
