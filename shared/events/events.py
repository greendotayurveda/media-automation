"""
Platform event definitions.
Every event published over Redis Streams is defined here.
All services import from this module — never define events locally.
"""
from enum import Enum


class EventType(str, Enum):
    """
    All platform events. Format: DOMAIN_ACTION
    Services publish these; the Workflow Engine routes them.
    """

    # ── Download lifecycle ────────────────────────────────────
    DOWNLOAD_QUEUED = "download.queued"
    DOWNLOAD_STARTED = "download.started"
    DOWNLOAD_PROGRESS = "download.progress"
    DOWNLOAD_COMPLETED = "download.completed"
    DOWNLOAD_FAILED = "download.failed"
    DOWNLOAD_RETRYING = "download.retrying"

    # ── Media received ────────────────────────────────────────
    MOVIE_RECEIVED = "movie.received"
    EPISODE_RECEIVED = "episode.received"
    MEDIA_RECEIVED = "media.received"          # generic

    # ── Analysis ─────────────────────────────────────────────
    MEDIA_ANALYZE_REQUESTED = "media.analyze.requested"
    MEDIA_ANALYZED = "media.analyzed"
    MEDIA_ANALYZE_FAILED = "media.analyze.failed"

    # ── Metadata ─────────────────────────────────────────────
    METADATA_IDENTIFY_REQUESTED = "metadata.identify.requested"
    METADATA_IDENTIFIED = "metadata.identified"
    METADATA_IDENTIFY_FAILED = "metadata.identify.failed"
    METADATA_UPDATED = "metadata.updated"

    # ── Subtitles ─────────────────────────────────────────────
    SUBTITLE_SEARCH_REQUESTED = "subtitle.search.requested"
    SUBTITLE_FOUND = "subtitle.found"
    SUBTITLE_DOWNLOADED = "subtitle.downloaded"
    SUBTITLE_NOT_FOUND = "subtitle.not_found"
    SUBTITLE_SYNCED = "subtitle.synced"

    # ── Quality ───────────────────────────────────────────────
    QUALITY_CHECK_REQUESTED = "quality.check.requested"
    QUALITY_CHECKED = "quality.checked"
    QUALITY_UPGRADE_AVAILABLE = "quality.upgrade.available"
    QUALITY_UPGRADED = "quality.upgraded"

    # ── File organization ─────────────────────────────────────
    FILE_ORGANIZE_REQUESTED = "file.organize.requested"
    FILE_ORGANIZED = "file.organized"
    FILE_MOVED = "file.moved"
    FILE_RENAMED = "file.renamed"
    FILE_DELETED = "file.deleted"

    # ── Duplicates ────────────────────────────────────────────
    DUPLICATE_DETECTED = "duplicate.detected"
    DUPLICATE_RESOLVED = "duplicate.resolved"

    # ── Storage ───────────────────────────────────────────────
    STORAGE_WARNING = "storage.warning"
    STORAGE_CRITICAL = "storage.critical"
    STORAGE_CLEANUP_COMPLETED = "storage.cleanup.completed"

    # ── Health ────────────────────────────────────────────────
    HEALTH_SCAN_STARTED = "health.scan.started"
    HEALTH_SCAN_COMPLETED = "health.scan.completed"
    HEALTH_ISSUE_FOUND = "health.issue.found"
    HEALTH_ISSUE_RESOLVED = "health.issue.resolved"

    # ── Jellyfin ─────────────────────────────────────────────
    JELLYFIN_REFRESH_REQUESTED = "jellyfin.refresh.requested"
    JELLYFIN_REFRESHED = "jellyfin.refreshed"

    # ── Media ready (end of pipeline) ─────────────────────────
    MEDIA_READY = "media.ready"
    MEDIA_FAILED = "media.failed"

    # ── Notifications ─────────────────────────────────────────
    NOTIFICATION_SEND = "notification.send"
    NOTIFICATION_SENT = "notification.sent"

    # ── Workflow ──────────────────────────────────────────────
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_STEP_COMPLETED = "workflow.step.completed"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_RETRYING = "workflow.retrying"


# Redis stream names
class StreamName(str, Enum):
    """Redis stream keys — one stream per domain."""
    DOWNLOADS = "stream:downloads"
    MEDIA = "stream:media"
    METADATA = "stream:metadata"
    SUBTITLES = "stream:subtitles"
    QUALITY = "stream:quality"
    FILES = "stream:files"
    HEALTH = "stream:health"
    STORAGE = "stream:storage"
    NOTIFICATIONS = "stream:notifications"
    WORKFLOWS = "stream:workflows"
    DEAD_LETTER = "stream:dead_letter"
