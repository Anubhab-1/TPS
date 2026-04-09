# Prioritized Task Processing System

This is a small backend system for submitting tasks and processing them asynchronously with strict priority handling.

The stack is:

- FastAPI for the API
- PostgreSQL for persistence
- Redis as the Celery broker/result backend
- Celery workers for background execution

I built it around three priority levels: `HIGH`, `MEDIUM`, and `LOW`.

## Architecture Overview

There are four main pieces in the project:

- The FastAPI app accepts requests to create tasks, fetch a single task, and list tasks.
- PostgreSQL stores the task records and their current state.
- Redis is used by Celery for queueing and result tracking.
- Three worker pools process tasks in the background.

The basic flow is:

1. A task is created through the API.
2. The task is saved in PostgreSQL with status `PENDING`.
3. The API sends it to Celery on the queue that matches its priority.
4. A worker picks it up, claims it safely in the database, and processes it.
5. The task ends up as `SUCCESS`, `FAILED`, or `DEAD`.

For local development, tables are created automatically on startup with `Base.metadata.create_all(...)`.

## Queue Design & Priority Handling

I used three separate queues:

- `high`
- `medium`
- `low`

This is the main design choice in the assignment.

I did not want to put everything into one queue and just store `priority` in the payload or DB. If that was done, a worker could grab a `LOW` task, and then a `HIGH` task arriving a moment later would still have to wait. That does not really enforce priority in a strict way.

With separate queues plus separate worker pools:

- `worker_high` only consumes `high`
- `worker_medium` only consumes `medium`
- `worker_low` only consumes `low`

So high priority work always has its own workers available. It is not competing directly with low priority work for the same consumer.

I also set `worker_prefetch_multiplier=1`. Without that, Celery can prefetch multiple messages ahead of time, which can blur the intended priority behavior. With prefetch set to 1, each worker only holds one task at a time.

## Concurrency & Race Condition Handling

The important part here is the claim step in `claim_task_for_processing`.

It uses:

`SELECT ... FOR UPDATE SKIP LOCKED`

The reason for this is simple: with multiple workers running, two workers might try to handle the same `PENDING` task at nearly the same time.

The DB lock prevents that:

- one worker locks the row
- it checks that the task is still `PENDING`
- it changes the status to `PROCESSING`
- then it commits

If another worker reaches the same task at the same time, `SKIP LOCKED` makes it skip that locked row instead of waiting on it.

That means only one worker can actually win the `PENDING -> PROCESSING` transition.

## Retry Strategy

Retries are handled manually in the app code instead of using `self.retry()`.

What happens on failure:

1. The worker catches the error.
2. The task is marked `FAILED`.
3. The retry count is increased.
4. If another retry is allowed, the task is reset back to `PENDING`.
5. It is re-queued with exponential backoff.

I kept the retry flow visible in the database because it makes the task lifecycle easier to understand when inspecting rows.

Current retry policy:

- max 3 total attempts
- 1 original attempt
- 2 retries

Backoff:

- retry 1 -> 2 seconds
- retry 2 -> 4 seconds

If the second retry also fails, the task is marked `DEAD`.

## Idempotency & At-Least-Once Processing

This system is designed around at-least-once delivery.

`acks_late=True` means the queue message is only acknowledged after the task function finishes. So if a worker crashes in the middle, the message can be delivered again.

`task_reject_on_worker_lost=True` helps with the same crash-recovery scenario. If the worker process dies, the message is not silently lost.

That still leaves the duplicate-delivery problem, which is why the DB claim step matters. Even if the same message is delivered again, the worker still has to claim the row in PostgreSQL. If the task is no longer `PENDING`, it is skipped.

So the broker gives at-least-once delivery, and the database guard prevents actual double-processing.

## Trade-offs

- Separate queues give much stronger priority guarantees, but low priority work can wait longer if high priority traffic is constant.
- `acks_late` improves reliability, but at-least-once delivery always means duplicate delivery is possible in edge cases.
- Manual retry handling gives better visibility in the DB, but it adds more code than Celery's built-in retry mechanism.
- PostgreSQL adds some overhead compared to an in-memory-only setup, but it gives durable state and makes the system easier to inspect.

## Running Locally

```bash
docker-compose up --build
```

Once it starts:

- API: `http://localhost:8000`
- Swagger docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/`

## API Reference

### `POST /tasks`

Create a new task.

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

Fetch a single task by ID.

```bash
curl "http://localhost:8000/tasks/11111111-1111-1111-1111-111111111111"
```

### `GET /tasks`

List tasks with optional filters.

```bash
curl "http://localhost:8000/tasks?status=PENDING&priority=HIGH&skip=0&limit=20"
```

The list response returns:

- `tasks`
- `total`
