from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PriorityEnum(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class StatusEnum(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DEAD = "DEAD"


class TaskCreate(BaseModel):
    payload: dict[str, Any]
    priority: PriorityEnum = PriorityEnum.MEDIUM


class TaskResponse(BaseModel):
    id: UUID
    payload: dict[str, Any]
    priority: PriorityEnum
    status: StatusEnum
    retry_count: int
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
