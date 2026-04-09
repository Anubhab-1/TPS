from celery import Celery
from kombu import Exchange, Queue

from app.config import settings


celery_app = Celery(
    "task-system",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_default_queue="medium",
    task_default_exchange="medium",
    task_default_exchange_type="direct",
    task_default_routing_key="medium",
    imports=("app.worker.task_processor",),
    task_queues=(
        Queue("high", Exchange("high", type="direct"), routing_key="high"),
        Queue("medium", Exchange("medium", type="direct"), routing_key="medium"),
        Queue("low", Exchange("low", type="direct"), routing_key="low"),
    ),
)
