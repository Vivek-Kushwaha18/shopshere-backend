from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)


DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/shop"


engine = create_async_engine(
    DATABASE_URL,
    echo=True
)


SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_db():
    async with SessionLocal() as session:
        yield session