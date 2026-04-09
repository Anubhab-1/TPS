from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


async_engine = create_async_engine(settings.DATABASE_URL)
engine = async_engine
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

sync_engine = create_engine(settings.SYNC_DATABASE_URL)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
