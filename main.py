from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database.database import engine

from app.models.base import Base
from app.models.user import User
from app.models.category import Category
from app.models.product import Product

from app.api.category import router as category_router
from app.api.product import router as product_router
from app.api.auth import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all
        )

    yield


app = FastAPI(
    title="ShopSphere API",
    description="AI-Powered Multi-Vendor E-Commerce Platform API",
    version="1.0.0",
    lifespan=lifespan,
)


# --------------------------------------------------
# CORS
# --------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Local frontend
        "http://localhost:3000",
        "http://127.0.0.1:3000",

        # Production frontend
        "https://shopshere-frontend-theta.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# API ROUTERS
# --------------------------------------------------

app.include_router(category_router)
app.include_router(product_router)
app.include_router(auth_router)


# --------------------------------------------------
# ROOT
# --------------------------------------------------

@app.get("/")
async def root():
    return {
        "message": "ShopSphere API is running"
    }


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }