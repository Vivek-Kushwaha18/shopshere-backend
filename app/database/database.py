import os

from dotenv import load_dotenv

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")


# Remove query parameters that asyncpg does not accept
if "?" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.split("?")[0]


engine = create_async_engine(
    DATABASE_URL,
    connect_args={
        "ssl": True
    },
    echo=False,
)


SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    async with SessionLocal() as session:
        yield session