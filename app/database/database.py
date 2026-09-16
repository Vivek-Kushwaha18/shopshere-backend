import os

from dotenv import load_dotenv

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)


# Load .env file
load_dotenv()


# Get database URL
DATABASE_URL = os.getenv("DATABASE_URL")


if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")


# Remove PostgreSQL parameters that asyncpg does not accept directly
DATABASE_URL = DATABASE_URL.replace("sslmode=require", "")
DATABASE_URL = DATABASE_URL.replace("channel_binding=require", "")
DATABASE_URL = DATABASE_URL.rstrip("?&")


# Create database engine
engine = create_async_engine(
    DATABASE_URL,
    connect_args={
        "ssl": True
    },
    echo=False,
)


# Create session
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Database dependency
async def get_db():
    async with SessionLocal() as session:
        yield session