
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

# For APIs
from app.api.auth import router as auth_router
from app.api.products import router as products_router

# For database
from app.database.database import engine

# For models
from app.models.base import Base
from app.models.user import User
from app.models.product import Product


app = FastAPI(
    title="ShopShere API",
)


# =========================
# CORS
# =========================

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "http://localhost:3000"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        "https://shopshere-frontend-theta.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# API ROUTES
# =========================

app.include_router(auth_router)
app.include_router(products_router)


# =========================
# DATABASE
# =========================

@app.on_event("startup")
async def create_tables():

    async with engine.begin() as connection:

        await connection.run_sync(
            Base.metadata.create_all
        )


# =========================
# ROOT API
# =========================

@app.get("/")
async def root():
    return {
        "message": "ShopSphere API is running"
    }
