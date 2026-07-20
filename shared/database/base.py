"""
SQLAlchemy declarative base and common model mixins.
All database models across all services inherit from these.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """
    Declarative base for all ORM models.
    Import and inherit from this in every service model.

    Example:
        from shared.database.base import Base, TimestampMixin

        class Movie(Base, TimestampMixin):
            __tablename__ = "movies"
            ...
    """
    pass


class UUIDMixin:
    """Adds a UUID primary key."""
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )


class TimestampMixin:
    """Adds created_at and updated_at audit timestamps."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds soft delete support (records are never physically deleted)."""
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = utc_now()


class AuditMixin(UUIDMixin, TimestampMixin):
    """
    Convenience mixin combining UUID primary key + timestamps.
    Use this for most tables.
    """
    pass
