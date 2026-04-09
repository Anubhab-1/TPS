from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Task
from app.schemas import StatusEnum, TaskCreate


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_task(db: AsyncSession, task_in: TaskCreate) -> Task:
    task = Task(
        payload=task_in.payload,
        priority=task_in.priority.value,
        status=StatusEnum.PENDING.value,
    )
    db.add(task)
    await db.flush()
    return task


async def get_task(db: AsyncSession, task_id: UUID) -> Task | None:
    return await db.get(Task, task_id)


async def list_tasks(
    db: AsyncSession,
    status: str | None,
    priority: str | None,
    skip: int,
    limit: int,
) -> tuple[list[Task], int]:
    filters = []

    if status is not None:
        filters.append(Task.status == status)

    if priority is not None:
        filters.append(Task.priority == priority)

    stmt = (
        select(Task)
        .where(*filters)
        .order_by(Task.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    count_stmt = select(func.count()).select_from(Task).where(*filters)

    tasks_result = await db.execute(stmt)
    total_result = await db.execute(count_stmt)

    tasks = tasks_result.scalars().all()
    total = total_result.scalar_one()

    return tasks, total


def claim_task_for_processing(sync_db: Session, task_id: UUID) -> Task | None:
    transaction = sync_db.begin()

    try:
        stmt = (
            select(Task)
            .where(Task.id == task_id)
            .with_for_update(skip_locked=True)
        )
        result = sync_db.execute(stmt)
        task = result.scalar_one_or_none()

        if task is None:
            transaction.rollback()
            return None

        if task.status != StatusEnum.PENDING.value:
            transaction.rollback()
            return None

        task.status = StatusEnum.PROCESSING.value
        task.updated_at = utcnow()

        sync_db.flush()
        transaction.commit()
        return task
    except Exception:
        transaction.rollback()
        raise


def mark_task_success(sync_db: Session, task_id: UUID) -> None:
    task = sync_db.get(Task, task_id)

    if task is None:
        return

    task.status = StatusEnum.SUCCESS.value
    task.error_message = None
    task.updated_at = utcnow()
    sync_db.commit()


def mark_task_failed(sync_db: Session, task_id: UUID, error: str, retry_count: int) -> None:
    task = sync_db.get(Task, task_id)

    if task is None:
        return

    task.retry_count = retry_count
    task.error_message = error
    task.status = StatusEnum.DEAD.value if retry_count >= 3 else StatusEnum.FAILED.value
    task.updated_at = utcnow()
    sync_db.commit()


def reset_task_to_pending(sync_db: Session, task_id: UUID, retry_count: int) -> None:
    task = sync_db.get(Task, task_id)

    if task is None:
        return

    task.status = StatusEnum.PENDING.value
    task.retry_count = retry_count
    task.updated_at = utcnow()
    sync_db.commit()
