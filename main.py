
from fastapi import FastAPI

import os 
# for apis
from app.api.auth import router as auth_router
from app.api.products import router as products_router
from fastapi.middleware.cors import CORSMiddleware





#for database or models
from app.database.database import engine

#for model
from app.models.base import Base
from app.models.user import User
from app.models.product import Product

app = FastAPI (
  title ="ShopShere API",
)
# also api part
app.include_router(auth_router)

app.include_router(products_router)

# data base part
@app.on_event("startup")
async def create_tables():

    async with engine.begin() as connection:

        await connection.run_sync(
            Base.metadata.create_all
        )
# comman
@app.get("/")
async def root():
    return {"message": "ShopSphere API is running"}

FRONTEND_URL = os.getenv(
  "FRONTEND_URL",
  "http://localhost:3000"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins="http://localhost:3000",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)