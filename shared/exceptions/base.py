"""
Platform exception hierarchy.
All services raise and catch exceptions from here — never define custom
exceptions in individual services unless they truly don't belong here.
"""
from typing import Any


class MediaPlatformError(Exception):
    """Root exception for the entire platform."""
    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def __str__(self) -> str:
        if self.context:
            return f"{self.message} | {self.context}"
        return self.message


# ── Configuration ─────────────────────────────────────────────────────────────

class ConfigurationError(MediaPlatformError):
    """Missing or invalid configuration."""


# ── Database ──────────────────────────────────────────────────────────────────

class DatabaseError(MediaPlatformError):
    """General database error."""


class RecordNotFoundError(DatabaseError):
    """Requested record does not exist."""
    def __init__(self, model: str, identifier: Any) -> None:
        super().__init__(f"{model} not found", identifier=str(identifier))
        self.model = model
        self.identifier = identifier


class DuplicateRecordError(DatabaseError):
    """Attempt to create a duplicate record."""


# ── Download ──────────────────────────────────────────────────────────────────

class DownloadError(MediaPlatformError):
    """General download error."""


class DownloadTimeoutError(DownloadError):
    """Download timed out."""


class InvalidFileError(DownloadError):
    """Downloaded file is corrupt or invalid."""


class StorageFullError(DownloadError):
    """Not enough disk space."""


# ── Media Analysis ────────────────────────────────────────────────────────────

class AnalysisError(MediaPlatformError):
    """FFprobe / MediaInfo analysis failed."""


class UnsupportedFormatError(AnalysisError):
    """File format is not supported."""


# ── Metadata ──────────────────────────────────────────────────────────────────

class MetadataError(MediaPlatformError):
    """Metadata lookup failed."""


class MovieNotIdentifiedError(MetadataError):
    """Could not match file to a movie/show in any provider."""


class ProviderRateLimitError(MetadataError):
    """External API rate limit hit."""
    def __init__(self, provider: str, retry_after: int | None = None) -> None:
        super().__init__(f"Rate limit hit for {provider}", retry_after=retry_after)
        self.provider = provider
        self.retry_after = retry_after


# ── Subtitles ─────────────────────────────────────────────────────────────────

class SubtitleError(MediaPlatformError):
    """Subtitle operation failed."""


class SubtitleNotFoundError(SubtitleError):
    """No subtitle found for the given movie/language."""


# ── Quality ───────────────────────────────────────────────────────────────────

class QualityError(MediaPlatformError):
    """Quality assessment failed."""


# ── File Operations ───────────────────────────────────────────────────────────

class FileOperationError(MediaPlatformError):
    """File move, rename, or delete failed."""


class FileNotFoundError(FileOperationError):
    """Expected file does not exist."""


# ── External Services ─────────────────────────────────────────────────────────

class ExternalServiceError(MediaPlatformError):
    """An external API / service call failed."""
    def __init__(self, service: str, message: str, status_code: int | None = None) -> None:
        super().__init__(message, service=service, status_code=status_code)
        self.service = service
        self.status_code = status_code


class JellyfinError(ExternalServiceError):
    """Jellyfin API call failed."""
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__("Jellyfin", message, status_code)


class TelegramError(ExternalServiceError):
    """Telegram bot API error."""
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__("Telegram", message, status_code)


# ── Workflow ──────────────────────────────────────────────────────────────────

class WorkflowError(MediaPlatformError):
    """Workflow execution error."""


class WorkflowStepError(WorkflowError):
    """A specific workflow step failed."""
    def __init__(self, step: str, message: str) -> None:
        super().__init__(message, step=step)
        self.step = step
