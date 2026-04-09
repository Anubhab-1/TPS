# Prioritized Task Processing System

This project is a small task-processing platform built around strict queue-level priority handling. Tasks are created through a FastAPI API, persisted in PostgreSQL, dispatched through Redis-backed Celery queues, and executed by dedicated worker pools for `high`, `medium`, and `low` priority work.

The API server auto-creates database tables on startup for local development, and Docker Compose brings up the full stack in one command.

## Architecture Overview

The system is split into four main components:

- FastAPI API layer: accepts task creation requests, exposes read/list endpoints, and dispatches work to Celery immediately after a task is stored.
- PostgreSQL: stores the durable source of truth for task metadata, status transitions, retry counts, timestamps, error messages, and Celery task IDs.
- Redis broker/backend: acts as the Celery broker for queue delivery and the result backend for Celery bookkeeping.
- Three dedicated Celery worker pools: one pool consumes only `high`, one only `medium`, and one only `low`.

At a high level, the flow is:

1. A client calls `POST /tasks`.
2. The API writes the task row to PostgreSQL with `PENDING` status.
3. The API enqueues a Celery message onto the queue that matches the task priority.
4. A worker from the corresponding pool receives the message and attempts to claim the database row safely.
5. The worker updates the task status based on success, failure, retry, or dead-letter outcome.

This design keeps the database responsible for durable state and history, while Redis and Celery handle delivery and execution.

## Queue Design & Priority Handling

This system uses three separate named queues:

- `high`
- `medium`
- `low`

This is intentionally different from putting every task into one shared queue with a `priority` field in the payload or database row.

With a single shared queue, a worker can legally take a `LOW` task simply because that message reached the queue first. If a `HIGH` task arrives a millisecond later, the worker has already committed to the low-priority work and the high-priority task must wait. That means the system is only sorting opportunistically, not enforcing hard priority.

With three separate queues and dedicated worker pools, priority becomes structural:

- High-priority work is consumed only by the `worker_high` pool.
- Medium-priority work is consumed only by the `worker_medium` pool.
- Low-priority work is consumed only by the `worker_low` pool.

There is no worker sharing across those queues, so `HIGH` work cannot be displaced by `LOW` work. The high-priority pool always remains reserved for high-priority traffic. This is structural priority, not naive sorting.

The workers also use `worker_prefetch_multiplier=1`. That setting matters because Celery workers otherwise prefetch multiple messages in advance. Prefetching can distort priority behavior by letting a worker hoard tasks before it is actually ready to execute them. Setting the multiplier to `1` means each worker only takes one task at a time, which keeps queue ownership honest and preserves the intended priority behavior.

## Concurrency & Race Condition Handling

The most important concurrency guard lives in `claim_task_for_processing`, which uses:

`SELECT ... FOR UPDATE SKIP LOCKED`

This pattern protects the task row at the database level when multiple workers, duplicate deliveries, or crash-driven redeliveries all compete to process the same logical task.

Without a lock, two workers could both observe a task as `PENDING` and both try to transition it to `PROCESSING`. That creates a race condition where the same task may execute twice.

The lock solves that problem:

- `FOR UPDATE` acquires a row-level lock on the selected task.
- Only one transaction can hold that lock at a time.
- The winning worker checks whether the status is still `PENDING`.
- If it is, that worker transitions the row to `PROCESSING` and commits.
- Any competing worker cannot make the same transition for the same row at the same time.

`SKIP LOCKED` is equally important. It tells PostgreSQL not to wait on already-locked rows. Instead of blocking, competing workers skip those rows immediately and move on. This keeps the worker fleet responsive under concurrency and avoids turning one in-flight task into a bottleneck for the whole system.

In practice, this means only one worker can successfully perform the `PENDING -> PROCESSING` transition for a given task row.

## Retry Strategy

Retries are managed manually in application code rather than using Celery's `self.retry()`.

The retry flow is:

1. The worker catches an exception.
2. The task row is updated to `FAILED` first, along with the new `retry_count` and latest `error_message`.
3. If the task is still eligible for another attempt, the row is reset from `FAILED` back to `PENDING`.
4. The task is re-queued onto the same priority queue with exponential backoff.

This pattern gives the database a clear, queryable state transition history and avoids a window where the task appears to have vanished from both the queue and the database. By recording the failure first and then resetting to `PENDING` before re-queueing, the task remains visible and explainable throughout its lifecycle.

The system allows a maximum of 3 total attempts: 1 original attempt plus 2 retries.

The exponential backoff schedule is:

- Retry 1: 2 seconds delay (`countdown = 2^1`)
- Retry 2: 4 seconds delay (`countdown = 2^2`)

After the 2nd retry fails, the task is permanently marked `DEAD` and is no longer retried.

## Idempotency & At-Least-Once Processing

This system is designed for at-least-once delivery rather than exactly-once delivery.

`acks_late=True` is a core part of that model. With late acknowledgements, the Redis message is not acknowledged and removed from the queue until the task function returns successfully. If a worker crashes midway through execution, the message is still considered unacknowledged and can be delivered again to another worker.

`task_reject_on_worker_lost=True` strengthens that behavior. If the worker process dies unexpectedly, the broker is told to reject the message rather than silently losing it.

Together, those settings improve crash recovery, but they also mean duplicate delivery is possible in failure scenarios. That is why the database claim guard exists.

The protection chain looks like this:

- Celery may redeliver a task message after a crash.
- A worker receives the redelivered message.
- `claim_task_for_processing` attempts to lock and validate the task row.
- If the task is no longer `PENDING`, the worker exits early and does not process it again.

That makes the system at-least-once at the broker level while still preventing actual double-execution at the application level for already-claimed or already-finished work.

## Trade-offs

- Separate queues give strict priority isolation, but `LOW` tasks can starve if `HIGH` traffic is constant. Keeping `worker_low` always running helps preserve forward progress for low-priority work.
- `acks_late` gives strong crash recovery and at-least-once delivery, but duplicate delivery is possible in edge cases. The database claim lock is what prevents duplicate execution from becoming duplicate business processing.
- Manual retries provide full visibility in PostgreSQL, including explicit status transitions and error history, but they add more code and operational logic than Celery's built-in retry mechanism.
- PostgreSQL adds more latency than a purely in-memory queue-only design, but it provides durable, queryable task history and makes the system observable, auditable, and debuggable.

## Running Locally

```bash
docker-compose up --build
```

After startup:

- API: `http://localhost:8000`
- OpenAPI docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/`

The API will create the database tables automatically on boot in development by running `Base.metadata.create_all(...)` during the FastAPI lifespan startup event.

## API Reference

### `POST /tasks`

Creates a new task, stores it in PostgreSQL, dispatches it to the Celery queue that matches its priority, and returns the created task.

```bash
curl -X POST "http://localhost:8000/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "payload": {
      "job": "generate-report",
      "account_id": 42
    },
    "priority": "HIGH"
  }'
```

### `GET /tasks/{task_id}`

Fetches one task by UUID.

```bash
curl "http://localhost:8000/tasks/11111111-1111-1111-1111-111111111111"
```

### `GET /tasks`

Lists tasks with optional filters for `status` and `priority`, plus pagination through `skip` and `limit`.

```bash
curl "http://localhost:8000/tasks?status=PENDING&priority=HIGH&skip=0&limit=20"
```

The list response includes:

- `tasks`: the matching task records
- `total`: the total number of rows matching the filter
