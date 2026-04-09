from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_priority", "status", "priority"),
        Index("ix_tasks_celery_task_id", "celery_task_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
