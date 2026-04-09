from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.database import get_db
from app.schemas import TaskCreate, TaskListResponse, TaskResponse
from app.worker.task_processor import process_task


router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "",
    response_model=TaskResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_task(
    task_in: TaskCreate,
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await crud.create_task(db, task_in)
    try:
        celery_result = process_task.apply_async(
            args=[str(task.id)],
            queue=task.priority.lower(),
        )
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to dispatch task to the worker queue",
        ) from exc

    task.celery_task_id = celery_result.id
    await db.commit()
    await db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, db: AsyncSession = Depends(get_db)) -> TaskResponse:
    task = await crud.get_task(db, task_id)

    if task is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    return task


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status: str | None = None,
    priority: str | None = None,
    skip: int = 0,
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
) -> TaskListResponse:
    tasks, total = await crud.list_tasks(
        db=db,
        status=status,
        priority=priority,
        skip=skip,
        limit=limit,
    )
    return TaskListResponse(tasks=tasks, total=total)
