from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.models
from app.api.tasks import router as tasks_router
from app.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="Prioritized Task Processing System",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(tasks_router)


@app.get("/")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
