"""
FFmpeg HEVC/H.265 video compressor with media verification.
Compresses H.264 / MPEG2 / VC1 videos to HEVC, copying audio and subtitle streams.
"""
import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from shared.config.settings import settings
from shared.exceptions.base import MediaPlatformError
from shared.logging.logger import get_logger

logger = get_logger("compression-service")

SKIP_CODECS = {"hevc", "h265", "av1"}


class CompressionError(MediaPlatformError):
    """Raised when video compression or verification fails."""
    pass


class MediaCompressor:
    """
    Evaluates video eligibility and performs lossy HEVC video compression
    preserving all audio, subtitle, and chapter metadata.
    """

    async def probe_media(self, file_path: Path) -> Dict[str, Any]:
        """Run ffprobe on file to get JSON metadata."""
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise CompressionError(f"ffprobe failed: {stderr.decode('utf-8', errors='replace')}")

        try:
            return json.loads(stdout.decode("utf-8"))
        except Exception as exc:
            raise CompressionError(f"Failed to parse ffprobe JSON: {exc}")

    def inspect_video_stream(self, probe_data: Dict[str, Any]) -> Tuple[Optional[str], float, int]:
        """Extract video codec, duration (seconds), and file size."""
        format_info = probe_data.get("format", {})
        duration = float(format_info.get("duration") or 0.0)
        size = int(format_info.get("size") or 0)

        video_codec = None
        for stream in probe_data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_codec = (stream.get("codec_name") or "").lower()
                break

        return video_codec, duration, size

    async def should_compress(self, file_path: Path) -> Tuple[bool, str]:
        """Check if video file is eligible for HEVC compression."""
        if not settings.compression_enabled:
            return False, "compression_disabled_in_settings"

        if not file_path.exists() or not file_path.is_file():
            return False, "file_not_found"

        if file_path.stat().st_size < 100 * 1024 * 1024:  # 100 MB minimum
            return False, "file_too_small"

        try:
            probe = await self.probe_media(file_path)
            codec, duration, size = self.inspect_video_stream(probe)
        except Exception as exc:
            logger.warning("Could not probe file for compression decision", file=str(file_path), error=str(exc))
            return False, f"probe_failed: {exc}"

        if not codec:
            return False, "no_video_stream_found"

        if codec in SKIP_CODECS:
            return False, f"already_{codec}"

        return True, f"eligible_{codec}_to_hevc"

    async def compress(self, file_path_str: str) -> Dict[str, Any]:
        """
        Compress video file using FFmpeg HEVC. Replaces file upon verification.
        """
        file_path = Path(file_path_str).resolve()
        logger.info("Evaluating video for compression", file=str(file_path))

        eligible, reason = await self.should_compress(file_path)
        if not eligible:
            logger.info("Skipping compression", file=str(file_path), reason=reason)
            return {
                "action": "skipped",
                "reason": reason,
                "file_path": str(file_path),
            }

        start_time = time.monotonic()
        orig_size = file_path.stat().st_size
        orig_probe = await self.probe_media(file_path)
        _, orig_duration, _ = self.inspect_video_stream(orig_probe)

        temp_out = file_path.with_name(f"{file_path.stem}_compressing_{int(time.time())}{file_path.suffix}")

        encoder = settings.compression_encoder.lower()
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
        ]

        if "vaapi" in encoder:
            # Setup hardware acceleration for VAAPI before the input
            cmd.extend([
                "-init_hw_device", "vaapi=intel:/dev/dri/renderD128",
                "-filter_hw_device", "intel"
            ])

        cmd.extend([
            "-i",
            str(file_path),
            "-c:v",
            encoder,
        ])

        if "vaapi" in encoder:
            # VAAPI requires uploading the frame to GPU memory
            cmd.extend(["-vf", "format=nv12,hwupload", "-global_quality", str(settings.compression_crf)])
        elif "qsv" in encoder:
            cmd.extend(["-global_quality", str(settings.compression_crf), "-preset", settings.compression_preset])
        elif "nvenc" in encoder:
            cmd.extend(["-cq", str(settings.compression_crf), "-preset", settings.compression_preset])
        else:
            cmd.extend([
                "-crf", str(settings.compression_crf),
                "-preset", settings.compression_preset,
                "-threads", "0",
                "-x265-params", "pool=*",
            ])

        cmd.extend([
            "-c:a",
            "copy",
            "-c:s",
            "copy",
            "-map",
            "0",
            str(temp_out),
        ])

        logger.info("Executing FFmpeg compression", cmd=" ".join(cmd), file=str(file_path))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace")[-500:]
                raise CompressionError(f"FFmpeg failed with exit code {proc.returncode}: {err_msg}")

            # Verify compressed file
            if not temp_out.exists() or temp_out.stat().st_size == 0:
                raise CompressionError("Compressed output file is empty or missing")

            comp_probe = await self.probe_media(temp_out)
            _, comp_duration, comp_size = self.inspect_video_stream(comp_probe)

            # Check duration match (within 3 seconds)
            if orig_duration > 0 and abs(orig_duration - comp_duration) > 3.0:
                raise CompressionError(f"Duration mismatch: original={orig_duration}s, compressed={comp_duration}s")

            elapsed_seconds = round(time.monotonic() - start_time, 2)

            # If compression didn't save space, discard and keep original
            if comp_size >= orig_size:
                logger.info(
                    "Compression did not reduce file size, keeping original",
                    orig_bytes=orig_size,
                    comp_bytes=comp_size,
                )
                if temp_out.exists():
                    temp_out.unlink()
                return {
                    "action": "skipped",
                    "reason": "no_size_reduction",
                    "file_path": str(file_path),
                    "original_size_bytes": orig_size,
                    "compressed_size_bytes": comp_size,
                }

            # Replace original file with compressed file safely
            temp_out.replace(file_path)

            savings_bytes = orig_size - comp_size
            savings_pct = round((savings_bytes / orig_size) * 100, 2)

            logger.info(
                "Compression completed & verified successfully",
                file=str(file_path),
                orig_mb=round(orig_size / (1024 * 1024), 2),
                comp_mb=round(comp_size / (1024 * 1024), 2),
                savings_pct=savings_pct,
                duration_sec=elapsed_seconds,
            )

            return {
                "action": "compressed",
                "file_path": str(file_path),
                "original_size_bytes": orig_size,
                "compressed_size_bytes": comp_size,
                "savings_bytes": savings_bytes,
                "savings_percent": savings_pct,
                "encoding_duration_seconds": elapsed_seconds,
            }

        except Exception as exc:
            logger.error("Compression failed or verification error", error=str(exc), file=str(file_path))
            if temp_out.exists():
                try:
                    temp_out.unlink()
                except Exception:
                    pass
            raise
