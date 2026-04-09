import logging
import random
import time
from uuid import UUID

from app.crud import (
    claim_task_for_processing,
    mark_task_failed,
    mark_task_success,
    reset_task_to_pending,
)
from app.database import SyncSessionLocal
from app.worker.celery_app import celery_app


logger = logging.getLogger(__name__)

PRIORITY_TO_QUEUE = {
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
}


@celery_app.task(bind=True, name="process_task", max_retries=2, acks_late=True)
def process_task(self, task_id: str) -> None:
    sync_db = SyncSessionLocal()
    task = None

    try:
        task_uuid = UUID(task_id)
        task = claim_task_for_processing(sync_db, task_uuid)

        if task is None:
            logger.info("Task already claimed or not pending, skipping")
            return

        original_queue = PRIORITY_TO_QUEUE.get(task.priority, "medium")

        if random.random() < 0.30:
            raise Exception("Simulated processing failure")

        time.sleep(2)
        mark_task_success(sync_db, task_uuid)
    except Exception as exc:
        if task is None:
            logger.exception("Task processing failed before claim")
            return

        new_retry_count = task.retry_count + 1
        error_str = str(exc)
        original_queue = PRIORITY_TO_QUEUE.get(task.priority, "medium")

        mark_task_failed(sync_db, task.id, error_str, new_retry_count)

        if new_retry_count < 3:
            reset_task_to_pending(sync_db, task.id, new_retry_count)
            process_task.apply_async(
                args=[task_id],
                queue=original_queue,
                countdown=2**new_retry_count,
            )
    finally:
        sync_db.close()
