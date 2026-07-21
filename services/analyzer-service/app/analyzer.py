"""
FFprobe & MediaInfo analysis executor.
Extracts technical media specs (resolution, codec, HDR, audio streams, container).
"""
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

from shared.exceptions.base import AnalysisError, FileNotFoundError
from shared.logging.logger import get_logger

logger = get_logger("media-analyzer")


class MediaAnalyzer:
    """
    Executes ffprobe to inspect video and audio stream specifications.
    """

    async def analyze(self, file_path: str) -> Dict[str, Any]:
        """Run ffprobe on file and return parsed technical specifications."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found for analysis: {file_path}")

        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            file_path,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise AnalysisError(f"ffprobe failed with code {process.returncode}: {stderr.decode()}")

            data = json.loads(stdout.decode())
            return self._parse_ffprobe_json(file_path, data)
        except Exception as exc:
            logger.error("FFprobe execution failed", file=file_path, error=str(exc))
            raise AnalysisError(f"Failed to analyze {file_path}", error=str(exc))

    def _parse_ffprobe_json(self, file_path: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Format raw ffprobe output into clean structured metadata."""
        streams = raw.get("streams", [])
        fmt = raw.get("format", {})

        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        resolution = self._determine_resolution(width, height)

        # HDR detection
        color_transfer = video_stream.get("color_transfer", "")
        color_primaries = video_stream.get("color_primaries", "")
        is_hdr = "smpte2084" in color_transfer or "arib-std-b67" in color_transfer or "bt2020" in color_primaries

        primary_audio = audio_streams[0] if audio_streams else {}

        return {
            "file_path": file_path,
            "file_name": Path(file_path).name,
            "container": fmt.get("format_name", "unknown").split(",")[0],
            "duration_seconds": round(float(fmt.get("duration", 0))),
            "file_size_bytes": int(fmt.get("size", 0)),
            "bitrate_kbps": round(int(fmt.get("bit_rate", 0)) / 1000) if fmt.get("bit_rate") else 0,
            # Video
            "resolution": resolution,
            "width": width,
            "height": height,
            "video_codec": video_stream.get("codec_name", "unknown"),
            "is_hdr": is_hdr,
            "hdr_format": "HDR10" if is_hdr else None,
            "frame_rate": video_stream.get("r_frame_rate", "24/1"),
            # Audio
            "audio_codec": primary_audio.get("codec_name", "unknown"),
            "audio_channels": str(primary_audio.get("channels", "2.0")),
            "audio_tracks_count": len(audio_streams),
            # Subtitles embedded
            "embedded_subtitles_count": len(subtitle_streams),
            "embedded_subtitle_languages": [
                s.get("tags", {}).get("language", "und") for s in subtitle_streams
            ],
        }

    @staticmethod
    def _determine_resolution(width: int, height: int) -> str:
        """Map dimensions to resolution standard strings."""
        if width >= 3800 or height >= 2100:
            return "2160p"
        elif width >= 1900 or height >= 1000:
            return "1080p"
        elif width >= 1200 or height >= 700:
            return "720p"
        elif width > 0:
            return "480p"
        return "unknown"
