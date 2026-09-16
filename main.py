from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# For APIs
from app.api.auth import router as auth_router
from app.api.product import router as product_router
from app.api.order import router as order_router

# For database
from app.database.database import engine

# For models
from app.models.base import Base
from app.models.user import User
from app.models.product import Product
from app.models.order import Order
from app.models.product_image import ProductImage


app = FastAPI(
    title="ShopShere API",
)


# =========================
# UPLOADS
# =========================

app.mount(
    "/uploads",
    StaticFiles(directory="uploads"),
    name="uploads"
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
app.include_router(product_router)
app.include_router(order_router)


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